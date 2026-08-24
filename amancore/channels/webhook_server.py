"""Webhook HTTP listener — exposes the WhatsApp webhook over local HTTP.

Transport only: all business logic stays in MessageCoordinator. Designed to
run on 127.0.0.1:8010 behind an HTTPS tunnel (e.g. Cloudflare). Uses the
standard library only (no new dependencies).

Endpoints:
    GET  /health              -> liveness probe
    GET  /webhook/whatsapp    -> Meta verification (hub.mode/verify_token/challenge)
    POST /webhook/whatsapp    -> signed event notifications -> coordinator

Security:
    - signature_required is honored: missing/invalid X-Hub-Signature-256 -> 403
    - malformed JSON -> 400
    - no secrets are ever logged or echoed
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..ids import utcnow
from ..log import get_logger

log = get_logger("channels.webhook_server")

MAX_BODY_BYTES = 1_000_000


_STATUS_RANK = {"processing": 1, "sent": 2, "delivered": 3, "read": 4}


def make_status_recorder(db):
    """OUT-204 (C3): delivery receipts keep outbox + inbox rows truthful.

    Status moves FORWARD only (monotonic rank) so an out-of-order webhook
    can never downgrade a message (e.g. 'read' back to 'delivered', or a
    stale receipt resurrecting a dead row). Unknown provider ids are
    reported instead of silently dropped.
    """

    def _record_status(provider_message_id, status, recipient_id=None):
        if not provider_message_id:
            return {"updated": False, "reason": "empty id"}
        cur = db.execute(
            "SELECT id FROM channel_messages WHERE wa_message_id = ? AND direction='out'",
            (provider_message_id,),
        ).fetchone()
        row = db.execute(
            "SELECT message_id, status FROM message_outbox WHERE provider_message_id = ?",
            (provider_message_id,),
        ).fetchone()
        if row is None:
            log.warning("status.unknown_provider_id pmid=%s status=%s",
                        provider_message_id[:24], status)
            return {"updated": False, "reason": "unknown id"}

        current = row["status"]
        if current in ("failed", "dead", "cancelled"):
            return {"updated": False, "reason": f"terminal {current}"}
        new_rank = _STATUS_RANK.get(status)
        if new_rank is not None and new_rank <= _STATUS_RANK.get(current, 0):
            return {"updated": False, "reason": "stale/out-of-order"}
        db.execute(
            "UPDATE message_outbox SET status = ? WHERE provider_message_id = ?",
            (status, provider_message_id),
        )
        if cur is None:
            src = db.execute(
                "SELECT recipient, lead_id, payload FROM message_outbox WHERE provider_message_id = ?",
                (provider_message_id,),
            ).fetchone()
            if src is not None:
                db.execute(
                    "INSERT INTO channel_messages"
                    " (direction, wa_id, lead_id, wa_message_id, body, status, created_at)"
                    " VALUES ('out', ?, ?, ?, ?, ?, ?)",
                    (src["recipient"], src["lead_id"], provider_message_id,
                     src["payload"] or "", status, utcnow()),
                )
                db.commit()
                return {"updated": True}
            # unknown id (e.g. AI auto-reply recorded via sync) — nothing to do
            return {"updated": False, "reason": "no inbox row"}
        db.execute(
            "UPDATE channel_messages SET status = ? WHERE id = ?", (status, cur["id"])
        )
        db.commit()
        return {"updated": True}

    return _record_status


def build_runtime(root: Path):
    """Assemble the live coordinator stack from configs (mirrors test wiring)."""
    from ..agents.sales import SalesAgent
    from ..business_brain.store import BrainStore
    from ..channels.coordinator import MessageCoordinator
    from ..channels.handover import HandoverService
    from ..channels.language import LanguageDetector
    from ..channels.outbox import MessageOutbox, OutboxWorker
    from ..channels.policy import ChannelPolicyEngine
    from ..channels.response_filter import ExternalResponseFilter
    from ..channels.whatsapp import WhatsAppAdapter
    from ..config import load_config
    from ..crm.service import CRMService
    from ..pricing.proposal import ProposalStore
    from ..pricing.snapshot import PricingSnapshotStore
    from ..sales.conversation_memory import ConversationMemory
    from ..sales.discovery import DiscoveryEngine
    from ..sales.followup import FollowupEngine
    from ..sales.handoff import HandoffService
    from ..sales.qualification import QualificationEngine
    from ..services.audit import AuditService
    from ..services.events import EventDispatcher, IdempotencyStore
    from ..services.owner_alert import send_owner_alert
    from ..skills.localization import LocalizationSkill
    from ..skills.objection_handling import ObjectionHandlingSkill
    from ..storage.db import open_database

    cfg = load_config(root)
    db = open_database(cfg.database_path, root / "amancore" / "storage" / "schema.sql")

    # Overlay owner-approved production state onto the whatsapp channel config.
    # channels.yaml keeps mode=mock by default; only a genuine audited
    # production enablement (production.yaml) switches the live provider.
    wa_cfg = dict(cfg.channels.get("whatsapp", {}))
    prod_env = (cfg.production.get("environment") or {})
    if prod_env.get("production_enabled") and prod_env.get("mode") == "production":
        wa_cfg["mode"] = "production"
        wa_cfg["environment"] = {
            "production_enabled": True,
            "mode": "production",
        }
        # credentials/identity come from env (never hardcoded in yaml)
        wa_cfg.setdefault("phone_number_id",
                          os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""))
        # api_version verified end-to-end live on 2026-08-24
        wa_cfg.setdefault("api_version",
                          os.environ.get("WHATSAPP_API_VERSION", "v21.0"))
    else:
        wa_cfg.setdefault("environment", {"production_enabled": False,
                                          "mode": prod_env.get("mode", "mock")})

    brain = BrainStore(root / "amancore" / "business_brain")
    audit = AuditService(db)
    dispatcher = EventDispatcher()
    adapter = WhatsAppAdapter(wa_cfg)
    outbox = MessageOutbox(db)
    policy = ChannelPolicyEngine(brain)
    try:
        outbox_cfg = dict(cfg.channels.get("outbox") or {})
    except Exception:  # noqa: BLE001 — config drift must never kill startup
        outbox_cfg = {}
    from ..compliance.guard import SendValve

    try:
        _comp = dict(cfg.app.get("compliance") or {})
    except Exception:  # noqa: BLE001
        _comp = {}
    valve = SendValve(db, tiers=_comp.get("warmup_tiers"),
                      tier_index=int(_comp.get("warmup_tier", 0)),
                      auto_cap=int(_comp.get("auto_send_cap", 50)))
    worker = OutboxWorker(
        outbox, {"whatsapp": adapter}, policy, audit=audit, dispatcher=dispatcher,
        claim_mode=str(outbox_cfg.get("claim_mode", "legacy")),
        stale_after_seconds=int(outbox_cfg.get("stale_after_seconds", 300)),
        owner_alert=send_owner_alert,
        send_valve=valve,
    )
    crm = CRMService(db)
    memory = ConversationMemory(crm)
    sales = SalesAgent(
        brain, crm, memory, DiscoveryEngine(), QualificationEngine(),
        ObjectionHandlingSkill(brain), FollowupEngine(), HandoffService(dispatcher),
        audit=audit, dispatcher=dispatcher,
    )
    from ..ops.cost_governor import CostGovernor

    cost_cfg = {}
    try:
        cost_cfg = dict(cfg.app.get("cost") or {})
    except Exception:  # noqa: BLE001 — governor must never block startup
        cost_cfg = {}
    governor = CostGovernor(cost_cfg)

    coordinator = MessageCoordinator(
        adapter, outbox, worker, sales, crm, memory,
        HandoverService(crm, dispatcher), ExternalResponseFilter(), policy,
        IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
        PricingSnapshotStore(db), ProposalStore(db),
        owner_alert=send_owner_alert,
        audit=audit, dispatcher=dispatcher,
        cost_governor=governor,
    )
    inbox = build_inbox_runtime(db, coordinator)

    if inbox is not None:
        def _record_inbound(direction, wa_id, lead_id, wa_message_id=None, body="",
                            quoted_wamid=None, **_):
            from ..ids import utcnow

            db.execute(
                "INSERT INTO channel_messages"
                " (direction, wa_id, lead_id, wa_message_id, body, status, created_at, quoted_wamid)"
                " VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                (direction, wa_id, lead_id, wa_message_id, body, utcnow(), quoted_wamid or None),
            )
            db.commit()

        coordinator.message_recorder = _record_inbound

        def _record_reaction(payload):
            """Customer reaction on our message: set/clear emoji chip in place."""
            wmid = payload.get("message_id")
            if not wmid:
                return
            emoji = payload.get("emoji") or None  # empty emoji == reaction removed
            cur = db.execute(
                "UPDATE channel_messages SET reaction=? WHERE wa_message_id=?",
                (emoji, wmid),
            )
            if cur.rowcount == 0 and emoji:
                # reaction on a message we have no row for — record as standalone note
                db.execute(
                    "INSERT INTO channel_messages"
                    " (direction, wa_id, lead_id, wa_message_id, body, status, created_at, reaction)"
                    " VALUES ('in', ?, NULL, ?, '', '', datetime('now'), ?)",
                    (payload.get("wa_id") or "", wmid, emoji),
                )
            db.commit()

        coordinator.status_recorder = make_status_recorder(db)
        coordinator.reaction_recorder = _record_reaction
        runtime_inbox_sync = lambda: sync_channel_messages(db)  # noqa: E731
    else:
        runtime_inbox_sync = lambda: None  # noqa: E731

    runtime = {"db": db, "adapter": adapter, "coordinator": coordinator,
               "inbox": inbox, "sync": runtime_inbox_sync}
    return runtime


def notify_owner_console(runtime, text: str) -> None:
    """Push a short report to the owner's Telegram chat (fire-and-forget)."""
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return
        payload = json.dumps({"chat_id": chat, "text": text[:3500],
                              "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:  # noqa: BLE001 — reporting must never break serving
        log.error("owner console notify failed: %s", exc)


def sync_channel_messages(db) -> None:
    """Reconcile outbound rows with the outbox so ticks/statuses stay truthful.

    - manual sends (channel_messages.outbox_message_id set): copy status +
      provider_message_id from their outbox row
    - AI/auto replies (outbox-only): adopt into channel_messages once
    """
    db.execute(
        """
        UPDATE channel_messages SET
          status = COALESCE((SELECT o.status FROM message_outbox o
                             WHERE o.message_id = channel_messages.outbox_message_id), status),
          wa_message_id = COALESCE(
              (SELECT o.provider_message_id FROM message_outbox o
               WHERE o.message_id = channel_messages.outbox_message_id), wa_message_id)
        WHERE direction='out' AND outbox_message_id IS NOT NULL
        """
    )
    db.execute(
        """
        INSERT INTO channel_messages
          (direction, wa_id, lead_id, wa_message_id, body, status, created_at, outbox_message_id)
        SELECT 'out', o.recipient, o.lead_id, o.provider_message_id,
               COALESCE(o.payload, ''), o.status, o.created_at, o.message_id
          FROM message_outbox o
         WHERE o.channel='whatsapp' AND o.message_type='text'
           AND o.provider_message_id IS NOT NULL
           AND o.created_at >= datetime('now', '-7 days')
           AND NOT EXISTS (
               SELECT 1 FROM channel_messages c WHERE c.outbox_message_id = o.message_id)
         ON CONFLICT(wa_message_id) WHERE wa_message_id IS NOT NULL DO NOTHING
        """
    )
    db.commit()


def build_inbox_runtime(db, coordinator):
    """Assemble the private owner inbox (auth + message store + send path)."""
    from .handover import HandoverService
    from .inbox import InboxConfig

    cfg = InboxConfig()
    if not cfg.configured:
        return None  # inbox disabled unless fully configured in env
    from ..crm.service import CRMService

    return {
        "config": cfg,
        "db": db,
        "crm": CRMService(db),
        "handover": HandoverService(CRMService(db)),
        "outbox": coordinator.outbox,
        "worker": coordinator.worker,
    }



def resolve_client_key(headers, peer_addr: str | None, trust_proxy: bool) -> str:
    """S2: proxy IP headers are trusted ONLY when the deployment flag says we
    actually sit behind that proxy — otherwise a client can spoof
    CF-Connecting-IP and rotate free brute-force buckets."""
    if trust_proxy:
        cf_ip = headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
    return peer_addr or "?"

class WebhookRequestHandler(BaseHTTPRequestHandler):
    server_version = "AmanCoreWebhook/1.0"

    # the runtime dict is attached to the HTTPServer instance
    @property
    def runtime(self) -> dict:
        return self.server.runtime

    @property
    def inbox(self):
        return self.runtime.get("inbox")

    def _inbox_route(self, path: str) -> tuple[object | None, str]:
        """Match /{slug}/{action} -> (inbox_runtime, action)."""
        inbox = self.inbox
        if inbox is None:
            return None, ""
        slug = inbox["config"].slug
        prefix = f"/{slug}/"
        if path.startswith(prefix):
            return inbox, path[len(prefix):]
        if path == f"/{slug}":
            return inbox, "login"
        return None, ""

    def log_message(self, fmt, *args):  # noqa: A003 — redacted, no bodies/secrets
        import re as _re

        line = fmt % args
        # never log tokens or signatures
        line = _re.sub(r"(hub\.verify_token=)[^&\s]+", r"\1<redacted>", line)
        line = _re.sub(r"(access_token=)[^&\s]+", r"\1<redacted>", line)
        entry = f"{self.address_string()} - {line}"
        print(entry, flush=True)
        log.info(entry)

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, page: str, extra_headers: dict | None = None) -> None:
        from .inbox import security_headers

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page.encode("utf-8"))))
        for k, v in security_headers().items():
            self.send_header(k, v)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def do_GET(self):  # noqa: N802 — stdlib naming
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, b"ok")
            return
        if parsed.path == "/webhook/whatsapp":
            qs = parse_qs(parsed.query)
            mode = (qs.get("hub.mode") or [""])[0]
            token = (qs.get("hub.verify_token") or [""])[0]
            challenge = (qs.get("hub.challenge") or [""])[0]
            result = self.runtime["adapter"].verify_webhook(mode, token, challenge)
            if result.get("verified"):
                self._send(200, result["challenge"].encode("utf-8"))
            else:
                self._send(403, b"verification failed")
            return
        inbox, action = self._inbox_route(parsed.path)
        if inbox is not None and not action.startswith("api"):
            return self._inbox_get(inbox, action, parsed.query)
        if inbox is not None and action.startswith("api/"):
            if not self._inbox_session_ok(inbox):
                self._send(403, b"forbidden", "application/json")
                return
            return self._inbox_api_get(inbox, action[len("api/"):], parse_qs(parsed.query))
        self._send(404, b"not found")

    def do_POST(self):  # noqa: N802 — stdlib naming
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        inbox, action = self._inbox_route(parsed.path)
        if inbox is not None:
            return self._inbox_post(inbox, action)
        if self.path != "/webhook/whatsapp":
            self._send(404, b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY_BYTES:
            self._send(400, b"bad content length")
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, b"malformed json")
            return
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            summary = self.runtime["coordinator"].handle_whatsapp_webhook(
                body, headers, raw_body=raw
            )
        except Exception as exc:  # noqa: BLE001 — respond, never leak internals
            log.error("webhook processing failed: %s", exc)
            self._send(500, b"internal error")
            return
        sync = self.runtime.get("sync")
        if sync:
            sync()
        if summary.get("replies"):
            try:
                frm = (body.get("entry", [{}])[0].get("changes", [{}])[0]
                       .get("value", {}).get("messages", [{}])[0].get("from", ""))
                if frm:
                    row = self.runtime["db"].execute(
                        "SELECT body FROM channel_messages WHERE direction='out'"
                        " AND wa_id=? ORDER BY id DESC LIMIT 1", (frm,)).fetchone()
                    last = (row["body"][:300] if row else "")
                    notify_owner_console(
                        self.runtime, "🤖 ردّيتُ على +{frm}:\n«{last}»".format(frm=frm, last=last))
                in_row = self.runtime["db"].execute(
                    "SELECT body FROM channel_messages WHERE direction='in'"
                    " AND wa_id=? AND body != '' ORDER BY id DESC LIMIT 1", (frm,)).fetchone()
                if in_row:
                    import threading as _th
                    from ..ops.learning import record_learning

                    if governor.allow(wa_id)[0]:
                        pass  # learning shares the customer's budget slot

                    _th.Thread(target=record_learning,
                               args=(frm, in_row["body"], last),
                               daemon=True).start()
            except Exception:  # noqa: BLE001
                pass
        if summary.get("status") == "rejected":
            self._send(403, json.dumps(summary).encode("utf-8"), "application/json")
            return
        self._send(200, json.dumps(summary).encode("utf-8"), "application/json")

    # ── private owner inbox ─────────────────────────────────────────────

    def _inbox_session_ok(self, inbox) -> bool:
        from .inbox import extract_session_cookie, verify_session_token

        token = extract_session_cookie(self.headers.get("Cookie"))
        return verify_session_token(inbox["config"].secret, token)

    def _client_key(self) -> str:
        inbox_cfg = self.runtime.get("inbox", {}).get("config") if self.runtime else None
        trust_proxy = getattr(inbox_cfg, "trust_proxy_ip", False)
        return resolve_client_key(self.headers, self.client_address[0], trust_proxy)

    def _inbox_get(self, inbox, action: str, query: str) -> None:
        from .inbox import render_inbox_page, render_login_page

        cfg = inbox["config"]
        if action in ("login", ""):
            already = self._inbox_session_ok(inbox)
            if already:
                return self._redirect(cfg.app_path)
            return self._send_html(200, render_login_page(cfg.login_path))
        if action == "app":
            if not self._inbox_session_ok(inbox):
                return self._redirect(cfg.login_path)
            base = f"/{cfg.slug}"
            return self._send_html(200, render_inbox_page(base, f"{base}/logout"))
        self._send(404, b"not found")

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_form(self) -> dict:
        from urllib.parse import parse_qs

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 10_000:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _read_json(self, max_bytes: int = 1_000_000) -> dict:
        """S4: tight default cap for JSON APIs; only the media-upload action
        opts into the larger bound (base64 ≈ 30MB binary needs ~40MB text)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= max_bytes:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _inbox_post(self, inbox, action: str) -> None:
        from .inbox import (
            SESSION_COOKIE,
            LoginRateLimiter,
            make_session_token,
            render_login_page,
            security_headers,
            verify_password,
        )

        cfg = inbox["config"]
        limiter: LoginRateLimiter = self.runtime.setdefault(
            "_login_limiter", LoginRateLimiter()
        )
        client = self._client_key()

        if action == "logout":
            # S4: unauthenticated force-logout was a one-click DoS on owners
            if not self._inbox_session_ok(inbox):
                return self._send(403, b"forbidden")
            secure_attr = "; Secure" if getattr(cfg, "secure_cookie", False) else ""
            expired = (f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; "
                       f"SameSite=Strict{secure_attr}")
            return self._send_html(303, "", {"Set-Cookie": expired, "Location": cfg.login_path})

        if action == "login":
            form = self._read_form()
            password = form.get("password", "")
            if limiter.is_locked(client):
                return self._send_html(429, render_login_page(cfg.login_path, "محاولات كثيرة — حاول بعد 10 دقائق"))
            if not password or not verify_password(password, cfg.password_hash):
                limiter.record_failure(client)
                import time as _t

                _t.sleep(1.0)  # brute-force damping
                return self._send_html(200, render_login_page(cfg.login_path, "كلمة مرور غير صحيحة"))
            limiter.reset(client)
            token = make_session_token(cfg.secret)
            secure_attr = "; Secure" if getattr(cfg, "secure_cookie", False) else ""
            cookie = (
                f"{SESSION_COOKIE}={token}; Path=/; Max-Age={12 * 60 * 60}; "
                f"HttpOnly; SameSite=Strict{secure_attr}"
            )
            return self._send_html(
                303, "", {"Set-Cookie": cookie, "Location": cfg.app_path}
            )

        if not self._inbox_session_ok(inbox):
            return self._send(403, b"forbidden")

        if action == "api/react":
            data = self._read_json()
            wa_id = str(data.get("wa_id") or "").strip()
            wamid = str(data.get("message_id") or "").strip()
            emoji = str(data.get("emoji") or "").strip()
            if not wa_id or not wamid:
                return self._send(400, b"bad request")
            try:
                self.runtime["adapter"].react(wa_id, wamid, emoji)
                return self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                log.error("reaction failed: %s", exc)
                return self._send(502, json.dumps({"ok": False, "error": str(exc)[:150]}).encode(), "application/json")

        if action == "api/read":
            data = self._read_json()
            wamids = data.get("message_ids") or []
            if not isinstance(wamids, list):
                return self._send(400, b"bad request")
            adapter = self.runtime["adapter"]
            ok_count = 0
            for wmid in wamids[:50]:
                if not isinstance(wmid, str) or not wmid.startswith("wamid."):
                    continue
                try:
                    adapter.mark_read(wmid)
                    ok_count += 1
                except Exception:  # noqa: BLE001 — best effort receipts
                    pass
            return self._send(200, json.dumps({"ok": True, "marked": ok_count}).encode(), "application/json")

        if action == "api/hide":
            data = self._read_json()
            msg_pk = data.get("id")
            if not isinstance(msg_pk, int):
                return self._send(400, b"bad request")
            inbox["db"].execute(
                "UPDATE channel_messages SET hidden = 1 WHERE id = ? AND direction='out'", (msg_pk,)
            )
            inbox["db"].commit()
            return self._send(200, json.dumps({"ok": True}).encode(), "application/json")

        if action == "api/send":
            data = self._read_json()
            wa_id = str(data.get("wa_id") or "").strip()
            text = str(data.get("text") or "").strip()
            media = data.get("media") or None
            if media is not None and (
                not isinstance(media, dict)
                or media.get("kind") not in ("image", "audio", "video", "document")
                or not isinstance(media.get("data_base64"), str)
                or len(media["data_base64"]) > 40_000_000  # ~30MB binary
            ):
                return self._send(400, json.dumps({"ok": False, "error": "bad media"}).encode(), "application/json")
            if (not wa_id) or (not text and not media):
                return self._send(400, b"bad request")
            if len(text) > 4096:
                return self._send(400, json.dumps({"ok": False, "error": "text too long"}).encode(), "application/json")
            reply_to = str(data.get("reply_to") or "").strip() or None
            if reply_to and not reply_to.startswith("wamid."):
                return self._send(400, b"bad reply_to")
            result = inbox_send_message(inbox, wa_id, text, media=media, reply_to=reply_to)
            status = 200 if result.get("ok") else 502
            return self._send(status, json.dumps(result).encode("utf-8"), "application/json")

        self._send(404, b"not found")

    def _inbox_api_get(self, inbox, resource: str, qs: dict) -> None:
        if resource == "leads":
            rows = inbox["db"].execute(
                """
                SELECT l.contact_whatsapp AS wa_id,
                       COALESCE(l.name, '') AS name,
                       COALESCE(c.mode, 'AI_ACTIVE') AS mode,
                       MAX(m.created_at) AS last_at,
                       (SELECT COUNT(*) FROM channel_messages u
                         WHERE u.wa_id = l.contact_whatsapp AND u.direction='in'
                           AND u.status IS NOT 'read' AND u.hidden = 0
                           AND u.wa_message_id LIKE 'wamid.%') AS unread
                  FROM leads l
             LEFT JOIN conversations c ON c.lead_id = l.lead_id
             LEFT JOIN channel_messages m ON m.wa_id = l.contact_whatsapp
              GROUP BY l.contact_whatsapp
              ORDER BY last_at DESC NULLS LAST
                 LIMIT 200
                """
            ).fetchall()
            payload = [dict(r) for r in rows]
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
        if resource == "messages":
            sync_channel_messages(inbox["db"])
            wa_id = (qs.get("wa_id") or [""])[0]
            before_id = (qs.get("before_id") or [""])[0]
            base_sql = """
                SELECT m.id, m.direction, m.body, m.status, m.created_at,
                       m.media_kind, m.media_ref, m.wa_message_id, m.reaction,
                       (SELECT substr(q.body, 1, 80) FROM channel_messages q
                         WHERE q.wa_message_id = m.quoted_wamid) AS quoted
                  FROM channel_messages m WHERE m.wa_id = ? AND m.hidden = 0
                """
            if before_id:  # U3: older-page fetch (client paginates past 500)
                rows = inbox["db"].execute(
                    base_sql + " AND m.id < ?"
                    " ORDER BY m.created_at DESC, m.id DESC LIMIT 200",
                    (wa_id, int(before_id)),
                ).fetchall()
                rows.reverse()
            else:
                # U3 fix: the DEFAULT page must be the NEWEST 500 (rendered
                # ascending) — the old ASC-LIMIT showed only ancient history
                # once a chat passed 500 messages.
                rows = inbox["db"].execute(
                    base_sql + " ORDER BY m.created_at DESC, m.id DESC LIMIT 500",
                    (wa_id,),
                ).fetchall()
                rows.reverse()
            payload = []
            for r in rows:
                d = dict(r)
                body = d.pop("body") or ""
                if d.get("media_kind"):
                    d["media"] = {"kind": d.pop("media_kind"), "ref": d.pop("media_ref")}
                    d["caption"] = body
                else:
                    d.pop("media_kind", None); d.pop("media_ref", None)
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and parsed.get("kind"):
                            d["media"] = {"kind": parsed["kind"], "ref": parsed.get("ref"),
                                          "filename": parsed.get("filename")}
                            d["caption"] = parsed.get("caption", "")
                        else:
                            d["caption"] = body
                    except (ValueError, TypeError):
                        d["caption"] = body
                payload.append(d)
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
        if resource == "media":
            ref = (qs.get("ref") or [""])[0]
            if not ref or not ref.isalnum():
                return self._send(400, b"bad ref")
            adapter = self.runtime["adapter"]
            provider = getattr(adapter, "provider", None)
            dl = getattr(provider, "download_media", None)
            if dl is None:
                return self._send(501, b"media download unavailable in mock mode")
            try:
                data, mime = dl(ref)
            except Exception as exc:  # noqa: BLE001
                log.error("media download failed: %s", exc)
                return self._send(502, b"download failed")
            return self._send(200, data, mime)
        self._send(404, b"not found")


def inbox_send_message(inbox, wa_id: str, text: str, media: dict | None = None,
                       reply_to: str | None = None) -> dict:
    """Owner manual reply: switch to HUMAN_ACTIVE, enqueue via policy-gated outbox."""
    import base64
    import tempfile
    import uuid

    from .handover import HandoverService
    from ..ids import utcnow
    from ..services.audit import AuditService

    crm = inbox["crm"]
    lead = crm.find_lead_by_whatsapp(wa_id)
    if lead is None:
        lead_id = crm.create_lead(contact_whatsapp=wa_id, source_channel="whatsapp")
        lead = crm.get_lead(lead_id)
    handover = HandoverService(crm)
    handover.set_mode(lead["lead_id"], "HUMAN_ACTIVE")

    message_type = "text"
    payload = text
    stored_body = text
    media_kind = media_ref = None

    if media:
        kind = media["kind"]
        mime = str(media.get("mime") or "application/octet-stream")
        filename = str(media.get("filename") or ("file." + mime.split("/")[-1]))
        raw = base64.b64decode(media["data_base64"])
        if len(raw) > 30 * 1024 * 1024:
            return {"ok": False, "error": "file too large (max 30MB)"}

        # voice notes: browser webm/opus -> WhatsApp requires ogg/amr/mp4/mpeg
        tmp_path = None
        if kind == "audio" and mime in ("audio/webm", "audio/webm;codecs=opus"):
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
                tf.write(raw)
                tmp_path = tf.name
            ogg_path = tmp_path.replace(".webm", ".ogg")
            import subprocess

            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path, "-c:a", "libopus", "-b:a", "48k", ogg_path],
                capture_output=True,
            )
            if proc.returncode == 0 and os.path.exists(ogg_path):
                raw = open(ogg_path, "rb").read()
                mime = "audio/ogg"
                filename = filename.rsplit(".", 1)[0] + ".ogg"
            else:
                mime = "audio/mp4"  # fallback container hint for Meta
            try:
                os.unlink(tmp_path)
                if os.path.exists(ogg_path):
                    os.unlink(ogg_path)
            except OSError:
                pass

        adapter = inbox.get("adapter")
        provider = getattr(adapter, "provider", None)
        upload_media = getattr(provider, "upload_media", None)
        if upload_media is None:
            # mock mode: no real upload possible — record intent only
            message_type = kind
            payload = {"caption": text, "filename": filename, "mock": True}
            media_kind, media_ref = kind, None
        else:
            media_id = upload_media(raw, mime, filename)
            message_type = kind
            payload = {"id": media_id}
            if text:
                payload["caption"] = text
            if kind == "document":
                payload["filename"] = filename
            media_kind, media_ref = kind, media_id
        stored_body = text

    if reply_to:
        if isinstance(payload, str):
            payload = {"_reply_to": reply_to, "body": payload}
        else:
            payload["_reply_to"] = reply_to

    mid = inbox["outbox"].enqueue(
        channel="whatsapp",
        recipient=wa_id,
        message_type=message_type,
        payload=payload,
        idempotency_key=f"wa-inbox:{uuid.uuid4()}",
        lead_id=lead["lead_id"],
    )
    results = inbox["worker"].drain(limit=5)
    sent = any(r.get("message_id") == mid and r.get("status") == "sent" for r in results)

    db = inbox["db"]
    db.execute(
        "INSERT INTO channel_messages"
        " (direction, wa_id, lead_id, body, status, created_at, media_kind, media_ref, outbox_message_id)"
        " VALUES ('out', ?, ?, ?, ?, ?, ?, ?, ?)",
        (wa_id, lead["lead_id"], stored_body, "queued" if not sent else "sent",
         utcnow(), media_kind, media_ref, mid),
    )
    db.commit()
    audit = AuditService(db)
    audit.record("channel.inbox_send", "lead", actor="owner", result="sent" if sent else "queued")
    sync_channel_messages(db)
    row = db.execute(
        "SELECT status FROM channel_messages WHERE outbox_message_id = ?", (mid,)
    ).fetchone()
    final_status = row["status"] if row else ("sent" if sent else "queued")
    return {
        "ok": True,
        "delivered": final_status == "sent" and message_type != "text" or sent,
        "status": final_status,
        "note": None,
    }


class WebhookServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, runtime: dict):
        super().__init__(addr, WebhookRequestHandler)
        self.runtime = runtime


def serve(root: Path, host: str = "127.0.0.1", port: int = 8010) -> int:
    """S3: refuse to boot with missing secrets for enabled integrations."""
    from ..config import validate_required_env

    from ..config import load_config as _lc

    _missing = validate_required_env(_lc(root))
    if _missing:
        for item in _missing:
            log.critical("MISSING SECRET: %s", item)
        raise SystemExit(f"refusing to start — {len(_missing)} required secret(s) missing")

    from ..log import setup_logging

    setup_logging()
    runtime = build_runtime(root)
    httpd = WebhookServer((host, port), runtime)

    # owner console: Telegram natural-language remote control (owner chat only)
    console = None
    try:
        from ..ops.telegram_console import TelegramOwnerConsole

        console = TelegramOwnerConsole(runtime)
        if not console.start():
            print("telegram console disabled: missing token/chat_id", flush=True)
    except Exception as exc:  # noqa: BLE001 — console must never block serving
        log.error("telegram console failed to start: %s", exc)

    stop = {"flag": False}

    def _shutdown(signum, frame):  # noqa: ARG001
        log.info("webhook server received signal %s — shutting down", signum)
        stop["flag"] = True
        # shutdown() must run on another thread (it blocks serve_forever's thread)
        import threading

        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _shutdown)
    log.info("webhook server listening on %s:%s (signature enforcement per config)", host, port)
    print(f"amancore webhook server listening on {host}:{port}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        if console:
            console.stop()
        httpd.server_close()
        runtime["db"].close()
        log.info("webhook server stopped cleanly")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AmanCore webhook listener")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    return serve(root, host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
