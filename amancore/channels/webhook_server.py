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
    return {"db": db, "adapter": adapter, "coordinator": coordinator}


class WebhookRequestHandler(BaseHTTPRequestHandler):
    server_version = "AmanCoreWebhook/1.0"

    # the runtime dict is attached to the HTTPServer instance
    @property
    def runtime(self) -> dict:
        return self.server.runtime

    def log_message(self, fmt, *args):  # noqa: A003 — redacted, no bodies/secrets
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self._send(404, b"not found")

    def do_POST(self):  # noqa: N802 — stdlib naming
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
