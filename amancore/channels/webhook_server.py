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
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..log import get_logger

log = get_logger("channels.webhook_server")

MAX_BODY_BYTES = 1_000_000


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
    brain = BrainStore(root / "amancore" / "business_brain")
    audit = AuditService(db)
    dispatcher = EventDispatcher()
    adapter = WhatsAppAdapter(dict(cfg.channels.get("whatsapp", {})))
    outbox = MessageOutbox(db)
    policy = ChannelPolicyEngine(brain)
    worker = OutboxWorker(outbox, {"whatsapp": adapter}, policy, audit=audit, dispatcher=dispatcher)
    crm = CRMService(db)
    memory = ConversationMemory(crm)
    sales = SalesAgent(
        brain, crm, memory, DiscoveryEngine(), QualificationEngine(),
        ObjectionHandlingSkill(brain), FollowupEngine(), HandoffService(dispatcher),
        audit=audit, dispatcher=dispatcher,
    )
    coordinator = MessageCoordinator(
        adapter, outbox, worker, sales, crm, memory,
        HandoverService(crm, dispatcher), ExternalResponseFilter(), policy,
        IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
        PricingSnapshotStore(db), ProposalStore(db),
        owner_alert=send_owner_alert,
        audit=audit, dispatcher=dispatcher,
    )
    inbox = build_inbox_runtime(db, coordinator)

    if inbox is not None:
        def _record_inbound(direction, wa_id, lead_id, wa_message_id=None, body="", **_):
            db.execute(
                "INSERT INTO channel_messages"
                " (direction, wa_id, lead_id, wa_message_id, body, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, '', datetime('now'))",
                (direction, wa_id, lead_id, wa_message_id, body),
            )
            db.commit()

        coordinator.message_recorder = _record_inbound

    return {"db": db, "adapter": adapter, "coordinator": coordinator, "inbox": inbox}


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
        return (self.headers.get("X-Forwarded-For") or self.client_address[0] or "?").split(",")[0].strip()

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

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 100_000:
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
            expired = f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
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
            cookie = (
                f"{SESSION_COOKIE}={token}; Path=/; Max-Age={12 * 60 * 60}; "
                "HttpOnly; SameSite=Strict"
            )
            return self._send_html(
                303, "", {"Set-Cookie": cookie, "Location": cfg.app_path}
            )

        if not self._inbox_session_ok(inbox):
            return self._send(403, b"forbidden")

        if action == "api/send":
            data = self._read_json()
            wa_id = str(data.get("wa_id") or "").strip()
            text = str(data.get("text") or "").strip()
            if not wa_id or not text or len(text) > 4096:
                return self._send(400, b"bad request")
            result = inbox_send_message(inbox, wa_id, text)
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
                       MAX(m.created_at) AS last_at
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
            wa_id = (qs.get("wa_id") or [""])[0]
            out_rows = inbox["db"].execute(
                """
                SELECT direction, body, status, created_at FROM (
                    SELECT 'in' AS direction, body, '' AS status, created_at
                      FROM channel_messages WHERE wa_id = ?
                    UNION ALL
                    SELECT 'out' AS direction, COALESCE(payload, ''), status, created_at
                      FROM message_outbox
                     WHERE channel='whatsapp' AND recipient = ? AND message_type='text'
                ) ORDER BY created_at ASC LIMIT 500
                """,
                (wa_id, wa_id),
            ).fetchall()
            return self._send(
                200, json.dumps([dict(r) for r in out_rows], ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        self._send(404, b"not found")


def inbox_send_message(inbox, wa_id: str, text: str) -> dict:
    """Owner manual reply: switch to HUMAN_ACTIVE, enqueue via policy-gated outbox."""
    import uuid

    from .handover import HandoverService
    from ..services.audit import AuditService

    crm = inbox["crm"]
    lead = crm.find_lead_by_whatsapp(wa_id)
    if lead is None:
        lead_id = crm.create_lead(contact_whatsapp=wa_id, source_channel="whatsapp")
        lead = crm.get_lead(lead_id)
    handover = HandoverService(crm)
    handover.set_mode(lead["lead_id"], "HUMAN_ACTIVE")
    mid = inbox["outbox"].enqueue(
        channel="whatsapp",
        recipient=wa_id,
        message_type="text",
        payload=text,
        idempotency_key=f"wa-inbox:{uuid.uuid4()}",
        lead_id=lead["lead_id"],
    )
    results = inbox["worker"].drain(limit=5)
    sent = any(r.get("message_id") == mid and r.get("status") == "sent" for r in results)
    audit = AuditService(inbox["db"])
    audit.record("channel.inbox_send", "lead", actor="owner", result="sent" if sent else "queued")
    db = inbox["db"]
    db.execute(
        "INSERT INTO channel_messages (direction, wa_id, lead_id, body, status, created_at)"
        " VALUES ('out', ?, ?, ?, ?, datetime('now'))",
        (wa_id, lead["lead_id"], text, "sent" if sent else "queued"),
    )
    db.commit()
    return {
        "ok": True,
        "delivered": sent,
        "note": None if sent else "queued — production mode required for real delivery",
    }


class WebhookServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, runtime: dict):
        super().__init__(addr, WebhookRequestHandler)
        self.runtime = runtime


def serve(root: Path, host: str = "127.0.0.1", port: int = 8010) -> int:
    runtime = build_runtime(root)
    httpd = WebhookServer((host, port), runtime)

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
