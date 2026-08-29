"""Bridge envelope contract tests + IDENTITY PARITY (owner spec §11/§16).

The critical guarantee: for the SAME platform user/message, the bridge
normalizer produces EXACTLY the same idempotency key and external_user_id
as the Graph adapters — no identity split, no duplicate lead, no history gap.
"""

from __future__ import annotations

import unittest

from amancore.channels.bridge_envelope import (
    EnvelopeError,
    normalize_envelope,
)
from amancore.channels.meta_channels import FacebookAdapter
from amancore.channels.whatsapp import WhatsAppAdapter


def _wa_envelope(wa_id: str = "15551234567", wamid: str = "wamid.PARITY1") -> dict:
    return {
        "event_id": "evt-1",
        "event_type": "message.received",
        "channel": "whatsapp",
        "account_id": "acc-1",
        "external_message_id": wamid,
        "sender": {"external_id": wa_id, "name": "Ahmed"},
        "message": {"type": "text", "text": "hi", "media": []},
        "timestamp": "2026-08-29T00:00:00+00:00",
        "metadata": {},
    }


class EnvelopeNormalizationTests(unittest.TestCase):
    def test_minimal_received_envelope(self):
        evt = normalize_envelope(_wa_envelope())
        self.assertEqual(evt.event_type, "message.received")
        self.assertEqual(evt.channel, "whatsapp")
        self.assertEqual(evt.payload["external_user_id"], "15551234567")
        self.assertEqual(evt.payload["text"], "hi")
        self.assertEqual(evt.payload["message_type"], "text")
        self.assertEqual(evt.metadata["provider_message_id"], "wamid.PARITY1")
        self.assertEqual(evt.metadata["account_id"], "acc-1")

    # ---- IDENTITY PARITY (owner spec §16) --------------------------------
    def test_whatsapp_identity_parity_with_graph_adapter(self):
        """same wamid + same wa_id → same idem key + same user id as Graph."""
        graph_body = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": "15551234567",
                              "profile": {"name": "Ahmed"}}],
                "messages": [{"from": "15551234567", "id": "wamid.PARITY1",
                              "type": "text",
                              "text": {"body": "hi"}}],
            }}]}],
        }
        graph_evt = WhatsAppAdapter({"mode": "mock"}).receive_webhook(graph_body)[0]
        bridge_evt = normalize_envelope(_wa_envelope())
        self.assertEqual(graph_evt.idempotency_key, bridge_evt.idempotency_key)
        self.assertEqual(graph_evt.payload["external_user_id"],
                         bridge_evt.payload["external_user_id"])
        self.assertEqual(graph_evt.metadata["provider_message_id"],
                         bridge_evt.metadata["provider_message_id"])
        self.assertEqual(graph_evt.channel, bridge_evt.channel)

    def test_facebook_identity_parity_with_graph_adapter(self):
        mid = "m_PARITY1"
        psid = "9876543210"
        graph_body = {"object": "page", "entry": [{"messaging": [{
            "sender": {"id": psid},
            "recipient": {"id": "PAGE"},
            "message": {"mid": mid, "text": "hello"},
        }]}]}
        graph_evt = FacebookAdapter({"mode": "mock"}).receive_webhook(graph_body)[0]
        bridge_evt = normalize_envelope({
            "event_type": "message.received", "channel": "facebook",
            "external_message_id": mid,
            "sender": {"external_id": psid, "name": ""},
            "message": {"type": "text", "text": "hello"},
        })
        self.assertEqual(graph_evt.idempotency_key, bridge_evt.idempotency_key)
        self.assertEqual(graph_evt.payload["external_user_id"],
                         bridge_evt.payload["external_user_id"])
        self.assertEqual(bridge_evt.idempotency_key, f"fb:{mid}")

    # ---- rejections (non-retryable) --------------------------------------
    def test_unknown_channel_rejected(self):
        with self.assertRaises(EnvelopeError) as ctx:
            normalize_envelope({"channel": "tiktok",
                                "event_type": "message.received"})
        self.assertEqual(ctx.exception.error_code, "UNKNOWN_CHANNEL")

    def test_missing_sender_rejected(self):
        env = _wa_envelope()
        env["sender"] = {}
        with self.assertRaises(EnvelopeError):
            normalize_envelope(env)

    def test_missing_message_id_rejected(self):
        env = _wa_envelope()
        env["external_message_id"] = ""
        with self.assertRaises(EnvelopeError):
            normalize_envelope(env)

    def test_bad_event_type_rejected(self):
        env = _wa_envelope()
        env["event_type"] = "something.else"
        with self.assertRaises(EnvelopeError):
            normalize_envelope(env)

    def test_media_without_payload_rejected(self):
        env = _wa_envelope()
        env["message"] = {"type": "image"}
        with self.assertRaises(EnvelopeError):
            normalize_envelope(env)

    # ---- side channels ----------------------------------------------------
    def test_reaction_envelope(self):
        evt = normalize_envelope({
            "event_type": "message.reaction", "channel": "whatsapp",
            "external_message_id": "wamid.RX1",
            "target_message_id": "wamid.OUT9",
            "sender": {"external_id": "15551234567"},
            "message": {"emoji": "👍"},
        })
        self.assertEqual(evt.event_type, "message.reaction")
        self.assertEqual(evt.payload["target_external_message_id"], "wamid.OUT9")
        self.assertEqual(evt.payload["emoji"], "👍")

    def test_status_envelope(self):
        evt = normalize_envelope({
            "event_type": "message.status", "channel": "whatsapp",
            "external_message_id": "wamid.OUT9", "status": "read",
            "sender": {"external_id": "15551234567"},
        })
        self.assertEqual(evt.event_type, "message.read")
        self.assertEqual(evt.payload["external_message_id"], "wamid.OUT9")

    def test_bad_status_rejected(self):
        with self.assertRaises(EnvelopeError):
            normalize_envelope({
                "event_type": "message.status", "channel": "whatsapp",
                "external_message_id": "wamid.X", "status": "teleported",
                "sender": {"external_id": "1"},
            })

    def test_media_envelope_with_reference(self):
        env = _wa_envelope()
        env["message"] = {"type": "image", "caption": "look",
                          "media": {"media_id": "media-7"}}
        evt = normalize_envelope(env)
        self.assertEqual(evt.payload["message_type"], "image")
        self.assertEqual(evt.payload["text"], "look")


if __name__ == "__main__":
    unittest.main()
