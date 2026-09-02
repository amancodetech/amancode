"""Bridge provider contract tests (owner spec §5/§17/§18) — same surface as
the Graph providers, + delivery_unknown → outbox `uncertain` (§15/§44)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fixtures.mock_bridge import MockBridge  # noqa: E402

from amancore.channels.bridge_meta import (  # noqa: E402
    BridgeFacebookAdapter,
    BridgeInstagramAdapter,
)
from amancore.channels.bridge_transport import BridgeError  # noqa: E402
from amancore.channels.bridge_whatsapp import BridgeWhatsAppAdapter  # noqa: E402
from amancore.channels.canonical import TEXT_ONLY  # noqa: E402
from tests.common import make_db  # noqa: E402

PROD_ENV = {"production_enabled": True, "mode": "production"}


def _cfg(base_url: str, shadow: bool = False) -> dict:
    return {"channel": "whatsapp", "mode": "bridge",
            "environment": dict(PROD_ENV),
            "bridge": {"base_url": base_url,
                       "token_env": "AMANCODE_BRIDGE_TOKEN",
                       "shadow": shadow,
                       "connect_retries": 0}}


class BridgeProviderSurfaceTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("AMANCODE_BRIDGE_TOKEN", None)
        os.environ["AMANCODE_BRIDGE_TOKEN"] = "test-bridge-token"

    def tearDown(self):
        os.environ.pop("AMANCODE_BRIDGE_TOKEN", None)
        if self._old is not None:
            os.environ["AMANCODE_BRIDGE_TOKEN"] = self._old

    def test_whatsapp_capabilities_match_graph_adapter(self):
        from amancore.channels.whatsapp import WhatsAppAdapter

        bridge = BridgeWhatsAppAdapter(_cfg("http://127.0.0.1:1"))
        graph = WhatsAppAdapter({"mode": "mock"})
        graph_caps = graph.capabilities()
        caps = bridge.capabilities()
        # bridge carries everything the Graph adapter carries, minus templates
        for field in ("text", "image", "audio", "video", "document",
                      "sticker", "reaction", "read_receipt", "reply_context"):
            self.assertEqual(getattr(caps, field), getattr(graph_caps, field),
                             field)
        self.assertFalse(caps.template)  # templates are a Graph-only feature

    def test_send_text_returns_provider_message_id(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            result = adapter.send("15551234567", "text", "hello there")
            self.assertTrue(result["provider_message_id"].startswith("wamid-"))
            self.assertEqual(result["status"], "sent")
        finally:
            bridge.stop()

    def test_text_clamped_to_4096_like_graph(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            adapter.send("15551234567", "text", "x" * 9999)
            sent_body = bridge.requests[0]["body"]
            self.assertEqual(len(sent_body["message"]["text"]), 4096)
        finally:
            bridge.stop()

    def test_reply_context_forwarded(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            adapter.send("15551234567", "text",
                         {"body": "reply", "_reply_to": "wamid.IN9"})
            message = bridge.requests[0]["body"]["message"]
            self.assertEqual(message["reply_to"], "wamid.IN9")
        finally:
            bridge.stop()

    def test_send_media_with_base64(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            result = adapter.send("15551234567", "image",
                                  {"data_base64": "aGVsbG8=", "mime": "image/png",
                                   "caption": "look"})
            self.assertTrue(result["provider_message_id"].startswith("wamid-"))
            message = bridge.requests[0]["body"]["message"]
            self.assertEqual(message["type"], "image")
            self.assertEqual(message["media"]["mime"], "image/png")
            self.assertEqual(message["media"]["caption"], "look")
        finally:
            bridge.stop()

    def test_send_media_requires_payload(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            with self.assertRaises(BridgeError) as ctx:
                adapter.send("15551234567", "image", {})
            self.assertEqual(ctx.exception.category, "invalid_request")
        finally:
            bridge.stop()

    def test_react_and_mark_read_via_send_raw_shape(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            ok = adapter.react("15551234567", "wamid.OUT1", "👍")
            self.assertTrue(ok["delivered"])
            ok = adapter.mark_read("wamid.IN1")
            self.assertTrue(ok["delivered"])
            self.assertEqual(bridge.requests[0]["path"], "/v1/messages/react")
            self.assertEqual(bridge.requests[1]["path"], "/v1/messages/read")
        finally:
            bridge.stop()

    def test_media_upload_download_via_provider(self):
        bridge = MockBridge()
        try:
            adapter = BridgeWhatsAppAdapter(_cfg(bridge.base_url))
            media_id = adapter.provider.upload_media(b"jpgbytes", "image/jpeg",
                                                     "photo.jpg")
            self.assertTrue(media_id.startswith("media-"))
            data, _ = adapter.provider.download_media(media_id)
            self.assertEqual(data, b"jpgbytes")
        finally:
            bridge.stop()

    def test_classify_error_maps_bridge_taxonomy(self):
        adapter = BridgeWhatsAppAdapter(_cfg("http://127.0.0.1:1"))
        self.assertEqual(adapter.classify_error(
            BridgeError("auth_required", "x")), ("auth_required", None))
        self.assertEqual(adapter.classify_error(
            BridgeError("rate_limited", "x", retry_after_seconds=7)),
            ("rate_limited", 7))
        self.assertEqual(adapter.classify_error(RuntimeError("x")),
                         (None, None))

    def test_identity_normalization_matches_graph(self):
        from amancore.channels.wa_errors import normalize_e164_digits

        adapter = BridgeWhatsAppAdapter(_cfg("http://127.0.0.1:1"))
        self.assertEqual(adapter.normalize_recipient("+1555 (123) 4567"),
                         normalize_e164_digits("+1555 (123) 4567"))

    def test_meta_bridge_adapters_text_only_and_psid_normalization(self):
        bridge = MockBridge()
        try:
            fb = BridgeFacebookAdapter({**_cfg(bridge.base_url),
                                        "channel": "facebook"})
            ig = BridgeInstagramAdapter({**_cfg(bridge.base_url),
                                         "channel": "instagram"})
            self.assertEqual(fb.capabilities().text, True)
            self.assertEqual(fb.capabilities().image, False)
            self.assertNotEqual(fb.capabilities(), TEXT_ONLY)  # read receipts on
            result = fb.send("1234567890123456", "text", "hi")
            self.assertTrue(result["provider_message_id"].startswith("wamid-"))
            self.assertEqual(fb.normalize_recipient("  Abc_123-x! "), "Abc_123-x")
            with self.assertRaises(BridgeError):
                ig.send("12345", "image", {"data_base64": "xx"})
        finally:
            bridge.stop()


class DeliveryUncertainOutboxTests(unittest.TestCase):
    """Owner spec §15: bridge timeout → `uncertain`, NEVER a blind retry."""

    def test_delivery_unknown_marks_uncertain(self):
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from tests.common import make_brain

        tmp = Path(__file__).parent.parent / "fixtures" / "_tmp_uncertain.db"
        db = make_db(tmp)
        try:
            brain = make_brain(Path(tmp).parent)
            outbox = MessageOutbox(db)
            adapter = _FlakyUncertainAdapter()
            policy = ChannelPolicyEngine(brain)
            worker = OutboxWorker(outbox, {"whatsapp": adapter}, policy)
            mid = outbox.enqueue(channel="whatsapp", recipient="15551234567",
                                 message_type="text", payload="hello")
            result = worker.process_one(outbox.get(mid))
            self.assertEqual(result["status"], "uncertain")
            row = outbox.get(mid)
            self.assertEqual(row["status"], "uncertain")
            self.assertIn("delivery_unknown", row["failure_reason"])
            # attempts untouched: reconciliation owns the next step
            self.assertEqual(row["attempts"], 0)
        finally:
            db.close()
            tmp.unlink(missing_ok=True)


class _FlakyUncertainAdapter:
    """Minimal adapter that always fails with delivery_unknown."""

    channel = "whatsapp"

    def send(self, recipient, message_type, payload):
        raise BridgeError("delivery_unknown",
                          "bridge send timeout — delivery state unknown")

    def classify_error(self, exc):
        if isinstance(exc, BridgeError):
            return exc.category, exc.retry_after_seconds
        return None, None


if __name__ == "__main__":
    unittest.main()
