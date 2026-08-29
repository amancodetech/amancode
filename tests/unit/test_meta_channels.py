"""P2-channels batch 1 — facebook/instagram adapters + /webhook/meta.

Contract parity with whatsapp: challenge handshake, fail-closed signature,
echo/receipt filtering, deterministic mock sends, policy-denies-until-enabled.
"""

import hashlib
import hmac
import json
import os
import unittest
from unittest import mock

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MSG = {
    "sender": {"id": "PSID123"},
    "recipient": {"id": "PAGE999"},
    "timestamp": 1756000000,
    "message": {"mid": "m_test_1", "text": "كم يبدأ السعر؟"},
}

ECHO = {
    "sender": {"id": "PAGE999"},
    "recipient": {"id": "PSID123"},
    "message": {"mid": "m_echo_1", "is_echo": True, "text": "ردنا"},
}

RECEIPT = {"sender": {"id": "PSID123"}, "recipient": {"id": "PAGE999"},
           "read": {"watermark": "1"}}


def _fb_cfg():
    from amancore.channels.meta_channels import FacebookAdapter

    return FacebookAdapter({"mode": "mock"})


def _ig_cfg():
    from amancore.channels.meta_channels import InstagramAdapter

    return InstagramAdapter({"mode": "mock", "ig_user_id": "1789TEST"})


class TestFacebookAdapter(unittest.TestCase):
    def test_challenge_handshake(self):
        with mock.patch.dict(os.environ, {"META_VERIFY_TOKEN": "amancore-test-token",
                                          "META_APP_SECRET": ""}):
            ad = _fb_cfg()
            res = ad.verify_webhook("subscribe", "amancore-test-token", "1158201444")
            assert res.get("verified") is True and res["challenge"] == "1158201444"
            bad = ad.verify_webhook("subscribe", "WRONG", "x")
        assert bad.get("verified") is not True

    def test_signature_fail_closed(self):
        secret = "s3cr3t"
        body = json.dumps({"object": "page", "entry": []}).encode()
        with mock.patch.dict(os.environ, {"META_APP_SECRET": secret,
                                          "WHATSAPP_APP_SECRET": ""}):
            ad = _fb_cfg()
            good = "sha256=" + hmac.new(secret.encode(), body,
                                        hashlib.sha256).hexdigest()
            assert ad.verify_signature(body, good) is True
            assert ad.verify_signature(body, "sha256=deadbeef") is False
            assert ad.verify_signature(body, None) is False

    def test_inbound_text_event(self):
        ad = _fb_cfg()
        evts = ad.receive_webhook({"object": "page",
                                   "entry": [{"messaging": [MSG]}]})
        assert len(evts) == 1
        e = evts[0]
        assert e.channel == "facebook" and e.actor_id == "PSID123"
        assert e.payload["text"] == "كم يبدأ السعر؟"
        assert e.idempotency_key == "fb:m_test_1"

    def test_echo_and_receipts_produce_nothing(self):
        ad = _fb_cfg()
        assert ad.receive_webhook({"object": "page",
                                   "entry": [{"messaging": [ECHO]}]}) == []
        assert ad.receive_webhook({"object": "page",
                                   "entry": [{"messaging": [RECEIPT]}]}) == []

    def test_mock_send_recorded(self):
        ad = _fb_cfg()
        r = ad.send("PSID123", "text", {"body": "أهلاً"})
        assert r["status"] == "sent"
        assert ad.provider.sent[0]["to"] == "PSID123"

    def test_policy_denies_until_enabled(self):
        """channels.yaml ships enabled+customer_messaging:true; sanity that a
        disabled block is denied by the SAME policy engine."""
        from amancore.channels.policy import ChannelPolicyEngine

        eng = ChannelPolicyEngine(None, {"facebook": {
            "enabled": False, "customer_messaging": False}})
        assert eng.evaluate_send("facebook", "text") == "deny"


class TestInstagramAdapter(unittest.TestCase):
    def test_inbound_ig_dm(self):
        ad = _ig_cfg()
        payload = {"object": "instagram",
                   "entry": [{"id": "1789TEST",
                              "messaging": [{
                                  "sender": {"id": "IGSID77"},
                                  "recipient": {"id": "1789TEST"},
                                  "message": {"mid": "im_1",
                                              "text": "hello"}}]}]}
        evts = ad.receive_webhook(payload)
        assert len(evts) == 1 and evts[0].channel == "instagram"
        assert evts[0].actor_id == "IGSID77"
        assert evts[0].idempotency_key == "ig:im_1"

    def test_messenger_payload_never_feeds_instagram(self):
        ad = _ig_cfg()
        assert ad.receive_webhook({"object": "page",
                                   "entry": [{"messaging": [MSG]}]}) == []


class TestRuntimeRegistration(unittest.TestCase):
    def test_channels_yaml_has_both_blocks(self):
        cfg = yaml.safe_load((ROOT / "configs" / "channels.yaml")
                             .read_text())
        for name in ("facebook", "instagram"):
            blk = cfg.get(name) or {}
            assert blk.get("enabled") is True
            assert blk.get("customer_messaging") is True
            assert blk.get("signature_required") is True

    def test_scheduler_registry_includes_meta(self):
        import sys

        sys.path.insert(0, str(ROOT))
        from amancore.ops.scheduler_adapter import build_adapters

        adapters = build_adapters()
        assert "facebook" in adapters and "instagram" in adapters
        assert adapters["facebook"].channel == "facebook"
