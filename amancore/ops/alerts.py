"""Owner Alerts — real transports with dedup/cooldown.

Contract (Phase 3H spec section 18):
  alert: id/severity/category/title/summary/evidence/action_required/
         related_entity/correlation_id/created_at/status

Severity routing:
  LOW     -> log only
  MEDIUM  -> store (dashboard/CLI)
  HIGH    -> store + owner transport
  CRITICAL-> store + owner transport immediately

Dedup: same dedup_key within cooldown window => one alert (no spam).
Channel is config-driven; availability is CHECKED, never assumed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.alerts")

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# ---- transports ----------------------------------------------------------
class AlertTransport:
    name = "log"

    def send(self, alert: dict) -> dict:
        raise NotImplementedError


class LogAlertTransport(AlertTransport):
    """Local sink — always available; never fails."""

    name = "log"

    def send(self, alert: dict) -> dict:
        log.warning(
            "[ALERT][%s][%s] %s — %s (action: %s)",
            alert["severity"], alert.get("category", ""), alert["title"],
            alert.get("summary", ""), alert.get("action_required", ""),
        )
        return {"transport": "log", "delivered": True}


class TelegramAlertTransport(AlertTransport):
    """Official Bot API — used only when TELEGRAM_BOT_TOKEN + CHAT_ID exist."""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, alert: dict) -> dict:
        import requests

        text = (
            f"🔔 *[{alert['severity']}] {alert.get('category', '')}*\n"
            f"*{alert['title']}*\n{alert.get('summary', '')}\n"
            f"*Action:* {alert.get('action_required', 'review')}"
        )
        resp = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"telegram send failed: {resp.status_code} {resp.text[:120]}")
        return {"transport": "telegram", "delivered": True}


class EmailAlertTransport(AlertTransport):
    """SMTP transport — used only when SMTP_* env vars exist."""

    name = "email"

    def __init__(self, host: str, user: str, password: str, to: str, port: int = 587):
        self.host, self.user, self.password, self.to = host, user, password, to
        try:
            self.port = int(port) if port else 587
        except (TypeError, ValueError):
            self.port = 587

    def send(self, alert: dict) -> dict:
        import smtplib
        from email.mime.text import MIMEText

        body = (
            f"[{alert['severity']}] {alert['title']}\n{alert.get('summary', '')}\n"
            f"Action required: {alert.get('action_required', 'review')}"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"AmanCore [{alert['severity']}] {alert['title']}"
        msg["To"] = self.to
        msg["From"] = self.user
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.user, self.password)
            server.sendmail(self.user, [self.to], msg.as_string())
        return {"transport": "email", "delivered": True}


def resolve_transport(config: dict | None = None, env: dict | None = None) -> AlertTransport:
    """Pick a transport from config + ACTUAL environment availability.

    Telegram is preferred when configured and available; email next; log
    always as a safe fallback. Never assumes credentials exist.
    """
    env = os.environ if env is None else env
    cfg = config or {}
    channel = cfg.get("channel", "log")

    if channel in ("telegram", "auto"):
        token = env.get(cfg.get("telegram_bot_token_env", "TELEGRAM_BOT_TOKEN"), "")
        chat_id = env.get(cfg.get("telegram_chat_id_env", "TELEGRAM_CHAT_ID"), "")
        if token and chat_id:
            return TelegramAlertTransport(token, chat_id)

    if channel in ("email", "auto"):
        host = env.get(cfg.get("smtp_host_env", "SMTP_HOST"), "")
        user = env.get(cfg.get("smtp_user_env", "SMTP_USER"), "")
        password = env.get(cfg.get("smtp_password_env", "SMTP_PASSWORD"), "")
        to = env.get(cfg.get("smtp_to_env", "SMTP_TO"), "")
        port = env.get(cfg.get("smtp_port_env", "SMTP_PORT"), "587")
        if host and user and password and to:
            return EmailAlertTransport(host, user, password, to, port=port)

    if channel in ("telegram", "email") and channel != "log":
        log.warning("alert channel %s configured but credentials missing — falling back to log", channel)
    return LogAlertTransport()


def transport_status(config: dict | None = None, env: dict | None = None) -> str:
    """'telegram (available)' | 'email (available)' | 'log (fallback)' | 'NOT_CONFIGURED'."""
    cfg = config or {}
    channel = cfg.get("channel", "log")
    env = os.environ if env is None else env
    if channel in ("telegram", "auto"):
        if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
            return "telegram (available)"
    if channel in ("email", "auto"):
        if env.get("SMTP_HOST") and env.get("SMTP_TO"):
            return "email (available)"
    if channel == "log":
        return "log (fallback)"
    return "NOT_CONFIGURED"


# ---- store + dispatcher ----------------------------------------------------
class AlertStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, alert: dict) -> str:
        alert_id = new_id()
        self.db.execute(
            "INSERT INTO alerts (alert_id, severity, category, title, summary, evidence, "
            " action_required, related_entity, correlation_id, fingerprint, dedup_key, "
            " status, transport, delivered, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
            (
                alert_id, alert["severity"], alert.get("category"), alert["title"],
                alert.get("summary", ""), json.dumps(alert.get("evidence", {}), ensure_ascii=False),
                alert.get("action_required", ""), alert.get("related_entity"),
                alert.get("correlation_id"), alert.get("fingerprint"), alert.get("dedup_key"),
                alert.get("transport"), 1 if alert.get("delivered") else 0, utcnow(),
            ),
        )
        self.db.commit()
        return alert_id

    def recent_by_dedup_key(self, dedup_key: str, window_minutes: int) -> dict | None:
        if not dedup_key:
            return None
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
        row = self.db.execute(
            "SELECT * FROM alerts WHERE dedup_key = ? AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 1",
            (dedup_key, cutoff),
        ).fetchone()
        return dict(row) if row else None

    def list(self, severity: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM alerts WHERE 1=1"
        params: list = []
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def counts(self) -> dict:
        rows = self.db.execute("SELECT severity, COUNT(*) AS c FROM alerts GROUP BY severity").fetchall()
        return {r["severity"]: r["c"] for r in rows}


class AlertDispatcher:
    def __init__(self, db: Database, config: dict | None = None,
                 transport: AlertTransport | None = None, owner_alert=None):
        self.db = db
        self.config = config or {}
        self.store = AlertStore(db)
        self.transport = transport or resolve_transport(self.config)
        self.cooldown = int(self.config.get("dedup_cooldown_minutes", 60))
        self.owner_alert = owner_alert  # legacy sink bridge (optional)

    def dispatch(self, *, severity: str, category: str = "", title: str, summary: str = "",
                 evidence: dict | None = None, action_required: str = "",
                 related_entity: str | None = None, correlation_id: str | None = None,
                 fingerprint: str | None = None) -> dict:
        severity = severity.upper()
        if severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {severity}")
        dedup_key = ""
        if fingerprint:
            dedup_key = fingerprint
        elif category or related_entity:
            dedup_key = f"{category}:{related_entity or ''}"
        existing = self.store.recent_by_dedup_key(dedup_key, self.cooldown)
        if existing is not None:
            return {"alert_id": existing["alert_id"], "deduplicated": True, "delivered": False,
                    "reason": "within cooldown window"}

        alert = {
            "severity": severity, "category": category, "title": title,
            "summary": summary, "evidence": evidence or {}, "action_required": action_required,
            "related_entity": related_entity, "correlation_id": correlation_id,
            "fingerprint": fingerprint, "dedup_key": dedup_key,
        }
        delivered = False
        transport_name = self.transport.name
        if severity in ("HIGH", "CRITICAL"):
            try:
                result = self.transport.send(alert)
                delivered = bool(result.get("delivered"))
                transport_name = result.get("transport", transport_name)
            except Exception as exc:  # noqa: BLE001 — alert must never crash the caller
                log.error("alert transport failed: %s", exc)
                alert["action_required"] = f"{action_required} (transport error: {exc})"
        elif severity == "LOW":
            log.info("[ALERT][LOW] %s", title)

        alert["transport"] = transport_name
        alert["delivered"] = delivered
        alert_id = self.store.create(alert)
        return {"alert_id": alert_id, "deduplicated": False, "delivered": delivered,
                "transport": transport_name}
