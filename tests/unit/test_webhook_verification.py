import json
import unittest

from amancore.channels.verification import WebhookVerifier
from amancore.channels.whatsapp import WhatsAppAdapter


class WebhookVerifierTest(unittest.TestCase):
    def test_verify_success(self):
        v = WebhookVerifier(verify_token="tok")
        r = v.verify("subscribe", "tok", "challenge123")
        self.assertTrue(r["verified"])
        self.assertEqual(r["challenge"], "challenge123")

    def test_verify_failure(self):
        v = WebhookVerifier(verify_token="tok")
        r = v.verify("subscribe", "wrong", "challenge123")
        self.assertFalse(r["verified"])

    def test_signature_verify(self):
        v = WebhookVerifier(app_secret="secret")
        body = b'{"hello":"world"}'
        import hashlib
        import hmac

        sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(v.verify_signature(body, sig))
        self.assertFalse(v.verify_signature(body, "sha256=deadbeef"))

    def test_signature_missing_secret(self):
        v = WebhookVerifier()
        self.assertFalse(v.verify_signature(b"x", "sha256=abc"))


class WhatsAppAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = WhatsAppAdapter({"mode": "mock"}, verifier=WebhookVerifier(verify_token="tok"))

    def _webhook(self):
        return {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": "551199999", "profile": {"name": "Ahmed"}}],
                "messages": [{"from": "551199999", "id": "wamid-1", "type": "text", "text": {"body": "مرحبا"}}],
            }}]}],
        }

    def test_receive_webhook_normalizes(self):
        events = self.adapter.receive_webhook(self._webhook())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "whatsapp.message.received")
        self.assertEqual(ev.channel, "whatsapp")
        self.assertEqual(ev.actor_id, "551199999")
        self.assertEqual(ev.payload["text"], "مرحبا")
        self.assertEqual(ev.idempotency_key, "wa:wamid-1")

    def test_webhook_verification(self):
        r = self.adapter.verify_webhook("subscribe", "tok", "ch123")
        self.assertTrue(r["verified"])

    def test_mock_send(self):
        r = self.adapter.send("551199999", "text", "hello")
        self.assertEqual(r["status"], "sent")
        self.assertTrue(r["provider_message_id"])

    def test_invalid_object_rejected(self):
        self.assertEqual(self.adapter.receive_webhook({"object": "other"}), [])

    def test_signature(self):
        body = json.dumps({"a": 1}, separators=(",", ":")).encode()
        self.assertFalse(self.adapter.verify_signature(body, None))


if __name__ == "__main__":
    unittest.main()
