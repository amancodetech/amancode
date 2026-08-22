"""Phase 3J tests — webhook HTTP listener: verification, signature, dedup, malformed.

Runs the real stdlib server on an ephemeral local port and exercises the
Meta webhook contract end-to-end against the live coordinator stack.
"""

import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from amancore.channels.webhook_server import WebhookServer

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
WA_ID = "551199999"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_body(text="I need a website", msg_id="wamid-1", wa_id=WA_ID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": wa_id, "profile": {"name": "Ahmed"}}],
            "messages": [{"from": wa_id, "id": msg_id, "type": "text", "text": {"body": text}}],
        }}]}],
    }


def build_signed_coordinator(tmp: Path):
    """Real coordinator stack with signature enforcement ON (production posture)."""
    from amancore.agents.sales import SalesAgent
    from amancore.business_brain.store import BrainStore
    from amancore.channels.coordinator import MessageCoordinator
    from amancore.channels.handover import HandoverService
    from amancore.channels.language import LanguageDetector
    from amancore.channels.outbox import MessageOutbox, OutboxWorker
    from amancore.channels.policy import ChannelPolicyEngine
    from amancore.channels.response_filter import ExternalResponseFilter
    from amancore.channels.whatsapp import WhatsAppAdapter
    from amancore.crm.service import CRMService
    from amancore.pricing.proposal import ProposalStore
    from amancore.pricing.snapshot import PricingSnapshotStore
    from amancore.sales.conversation_memory import ConversationMemory
    from amancore.sales.discovery import DiscoveryEngine
    from amancore.sales.followup import FollowupEngine
    from amancore.sales.handoff import HandoffService
    from amancore.sales.qualification import QualificationEngine
    from amancore.services.audit import AuditService
    from amancore.services.events import EventDispatcher, IdempotencyStore
    from amancore.skills.localization import LocalizationSkill
    from amancore.skills.objection_handling import ObjectionHandlingSkill
    from tests.common import make_brain, make_db

    db = make_db(tmp / "live.db")
    brain = make_brain(tmp)
    audit = AuditService(db)
    dispatcher = EventDispatcher()
    adapter = WhatsAppAdapter({"mode": "mock", "signature_required": True})
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
    coord = MessageCoordinator(
        adapter, outbox, worker, sales, crm, memory,
        HandoverService(crm, dispatcher), ExternalResponseFilter(), policy,
        IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
        PricingSnapshotStore(db), ProposalStore(db),
        owner_alert=lambda level, msg, corr: None,
        audit=audit, dispatcher=dispatcher,
    )
    return {"db": db, "adapter": adapter, "coordinator": coord}


class WebhookServerTest(unittest.TestCase):
    """HTTP transport behavior against the REAL server + coordinator."""

    @classmethod
    def setUpClass(cls):
        cls._old_env = {k: os.environ.get(k) for k in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET")}
        os.environ["WHATSAPP_VERIFY_TOKEN"] = VERIFY_TOKEN
        os.environ["WHATSAPP_APP_SECRET"] = APP_SECRET
        cls.tmp = tempfile.TemporaryDirectory()
        runtime = build_signed_coordinator(Path(cls.tmp.name))
        cls.crm_cls = None
        cls.httpd = WebhookServer(("127.0.0.1", 0), runtime)
        cls.runtime = runtime
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.runtime["db"].close()
        for k, v in cls._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.tmp.cleanup()

    # ---- helpers --------------------------------------------------------
    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _post(self, path, payload: bytes, headers=None):
        req = urllib.request.Request(self.base + path, data=payload, method="POST",
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read() or b"{}"
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode("utf-8", "replace")}

    # ---- GET /health ------------------------------------------------------
    def test_health_endpoint(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"ok")

    # ---- GET verification (Meta contract) ----------------------------------
    def test_get_verification_valid_token_returns_challenge(self):
        status, body = self._get(
            f"/webhook/whatsapp?hub.mode=subscribe&hub.verify_token={VERIFY_TOKEN}&hub.challenge=12345"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"12345")

    def test_get_verification_bad_token_rejected(self):
        status, _ = self._get(
            "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=WRONG&hub.challenge=12345"
        )
        self.assertEqual(status, 403)

    # ---- POST events -------------------------------------------------------
    def test_post_missing_signature_rejected_403(self):
        payload = json.dumps(webhook_body(msg_id="wamid-http-nosig")).encode()
        status, data = self._post("/webhook/whatsapp", payload, {})
        self.assertEqual(status, 403)
        self.assertEqual(data.get("reason"), "invalid signature")

    def test_post_invalid_signature_rejected_403(self):
        payload = json.dumps(webhook_body(msg_id="wamid-http-badsig")).encode()
        status, data = self._post("/webhook/whatsapp", payload,
                                  {"X-Hub-Signature-256": "sha256=" + "0" * 64})
        self.assertEqual(status, 403)
        self.assertEqual(data.get("reason"), "invalid signature")

    def test_post_malformed_json_rejected_400(self):
        raw = b"{not-json"
        status, _ = self._post("/webhook/whatsapp", raw,
                               {"X-Hub-Signature-256": _sign(APP_SECRET, raw)})
        self.assertEqual(status, 400)

    def test_post_valid_signed_event_processed(self):
        raw = json.dumps(webhook_body(msg_id="wamid-http-ok")).encode()
        status, data = self._post("/webhook/whatsapp", raw,
                                  {"X-Hub-Signature-256": _sign(APP_SECRET, raw)})
        self.assertEqual(status, 200)
        self.assertEqual(data.get("received"), 1)
        self.assertEqual(data.get("processed"), 1)

    def test_post_duplicate_event_deduplicated_no_second_reply(self):
        raw = json.dumps(webhook_body(msg_id="wamid-http-dup")).encode()
        sig = {"X-Hub-Signature-256": _sign(APP_SECRET, raw)}
        status1, data1 = self._post("/webhook/whatsapp", raw, sig)
        status2, data2 = self._post("/webhook/whatsapp", raw, sig)
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)
        self.assertEqual(data1["processed"], 1)
        self.assertEqual(data2["processed"], 0)
        self.assertEqual(data2["duplicates"], 1)

    def test_unknown_path_404(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
