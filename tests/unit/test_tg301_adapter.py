"""TG-301 — TelegramAdapter contract surface (Phase 24)."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from amancore.channels.canonical import ChannelCapabilities  # noqa: E402
from amancore.channels.contract import ChannelAdapter  # noqa: E402
from amancore.channels.telegram import (  # noqa: E402
    MockTelegramProvider, TelegramAdapter,
)


def _adapter(**cfg):
    base = {"mode": "mock", "signature_required": False}
    base.update(cfg)
    return TelegramAdapter(base)


def _update(update_id=9001, user_id=777000, chat_id=777000, text="مرحبا",
            message_id=551, first="Omar", last="", reply_to=None):
    msg = {
        "message_id": message_id,
        "from": {"id": user_id, "is_bot": False, "first_name": first,
                 "last_name": last},
        "chat": {"id": chat_id, "type": "private"},
        "date": 1777777777,
        "text": text,
    }
    if reply_to:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": msg}


class Contract(unittest.TestCase):
    def test_satisfies_channel_adapter_contract(self):
        a = _adapter()
        self.assertIsInstance(a, ChannelAdapter)
        for m in ("send", "receive_webhook", "verify_webhook", "verify_signature",
                  "capabilities", "normalize_recipient", "classify_error",
                  "signature_header_name"):
            self.assertTrue(callable(getattr(a, m)), m)

    def test_capabilities_smallest_safe_surface(self):
        caps = _adapter().capabilities()
        self.assertIsInstance(caps, ChannelCapabilities)
        self.assertTrue(caps.text)
        self.assertTrue(caps.reply_context)
        for unsupported in ("image", "audio", "video", "document", "sticker",
                            "template", "reaction", "read_receipt"):
            self.assertFalse(getattr(caps, unsupported), unsupported)

    def test_signature_header_is_telegram_official(self):
        self.assertEqual(_adapter().signature_header_name(),
                         "x-telegram-bot-api-secret-token")

    def test_no_get_handshake_fail_closed(self):
        res = _adapter().verify_webhook("subscribe", "whatever", "ch")
        self.assertFalse(res.get("verified"))


class RecipientNormalization(unittest.TestCase):
    def test_numeric_chat_id(self):
        self.assertEqual(_adapter().normalize_recipient("777000"), "777000")

    def test_negative_group_chat_id(self):
        self.assertEqual(_adapter().normalize_recipient("-1001234"), "-1001234")

    def test_rejects_e164_style_and_garbage(self):
        for bad in ("+905551112233", "90555 111 22 33", "", None, "user@name"):
            with self.assertRaises(ValueError):
                _adapter().normalize_recipient(bad)


class SignatureVerification(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("TELEGRAM_CUSTOMER_WEBHOOK_SECRET", None)
        os.environ["TELEGRAM_CUSTOMER_WEBHOOK_SECRET"] = "s3cret-value"
        self.a = TelegramAdapter({"mode": "mock", "signature_required": True})

    def tearDown(self):
        if self._old is None:
            os.environ.pop("TELEGRAM_CUSTOMER_WEBHOOK_SECRET", None)
        else:
            os.environ["TELEGRAM_CUSTOMER_WEBHOOK_SECRET"] = self._old

    def test_valid_secret_accepted(self):
        self.assertTrue(self.a.verify_signature(b"{}", "s3cret-value"))

    def test_wrong_secret_rejected(self):
        self.assertFalse(self.a.verify_signature(b"{}", "wrong"))

    def test_missing_header_rejected(self):
        self.assertFalse(self.a.verify_signature(b"{}", None))
        self.assertFalse(self.a.verify_signature(b"{}", ""))

    def test_unconfigured_secret_fails_closed(self):
        a = TelegramAdapter({"mode": "mock", "signature_required": True})
        self.assertFalse(a.verify_signature(b"{}", "anything"))


class InboundNormalization(unittest.TestCase):
    def setUp(self):
        self.a = _adapter()

    def test_valid_update_becomes_single_canonical_event(self):
        evs = self.a.receive_webhook(_update(first="Omar", last="K",
                                             text="أريد موقع شركة، كم السعر؟"))
        self.assertEqual(len(evs), 1)
        ev = evs[0]
        self.assertEqual(ev.event_type, "message.received")
        self.assertEqual(ev.channel, "telegram")
        self.assertEqual(ev.idempotency_key, "tg:9001")
        self.assertEqual(ev.payload["external_user_id"], "777000")
        self.assertEqual(ev.payload["external_conversation_id"], "777000")
        self.assertEqual(ev.payload["text"], "أريد موقع شركة، كم السعر؟")
        self.assertEqual(ev.payload["name"], "Omar K")
        self.assertEqual(ev.metadata["provider_message_id"], "551")
        self.assertEqual(ev.metadata["chat_id"], "777000")

    def test_reply_threading_preserved(self):
        evs = self.a.receive_webhook(_update(reply_to=549))
        self.assertEqual(evs[0].payload["reply_to_external_message_id"], "549")

    def test_malformed_shapes_ignored_not_crashing(self):
        self.assertEqual(self.a.receive_webhook(None), [])
        self.assertEqual(self.a.receive_webhook("nope"), [])
        self.assertEqual(self.a.receive_webhook({"message": {}}), [])
        self.assertEqual(self.a.receive_webhook(
            {"update_id": 1, "message": {"chat": {}, "from": {}}}), [])

    def test_non_message_updates_ignored(self):
        self.assertEqual(self.a.receive_webhook(
            {"update_id": 2, "edited_message": _update()["message"]}), [])
        self.assertEqual(self.a.receive_webhook(
            {"update_id": 3, "callback_query": {"id": "x"}}), [])


class Outbound(unittest.TestCase):
    def test_send_through_mock_provider_records_payload(self):
        prov = MockTelegramProvider()
        a = TelegramAdapter({"mode": "mock"}, provider=prov)
        res = a.send("777000", "text", {"body": "hello"})
        self.assertEqual(res["status"], "sent")
        self.assertTrue(res["provider_message_id"])
        self.assertEqual(prov.sent[0]["recipient"], "777000")
        self.assertEqual(prov.sent[0]["payload"]["text"], "hello")

    def test_send_clamps_to_configured_limit(self):
        prov = MockTelegramProvider()
        a = TelegramAdapter({"mode": "mock", "max_text_length": 10}, provider=prov)
        a.send("-10099", "text", {"body": "x" * 500})
        self.assertLessEqual(len(prov.sent[0]["payload"]["text"]), 10)

    def test_send_reply_parameters(self):
        prov = MockTelegramProvider()
        a = TelegramAdapter({"mode": "mock"}, provider=prov)
        a.send("777000", "text", {"body": "r", "_reply_to": "551"})
        self.assertEqual(prov.sent[0]["payload"]["reply_parameters"],
                         {"message_id": 551})

    def test_unsupported_type_refused_locally(self):
        from amancore.channels.telegram import TelegramAPIError

        prov = MockTelegramProvider()
        a = TelegramAdapter({"mode": "mock"}, provider=prov)
        with self.assertRaises(TelegramAPIError):
            a.send("777000", "video", {"x": 1})
        self.assertEqual(prov.sent, [])

    def test_classify_error_passthrough_for_foreign_exceptions(self):
        self.assertEqual(_adapter().classify_error(ValueError("x")), (None, None))


if __name__ == "__main__":
    unittest.main()
