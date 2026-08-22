import copy
import unittest

from amancore.channels.whatsapp import GraphWhatsAppProvider, WhatsAppAdapter
from amancore.errors import ProductionNotEnabledError
from amancore.production.gate import ProductionGateService

MOCK_PRODUCTION_CONFIG = {
    "environment": {"mode": "mock", "api_version": "v24.0", "webhook_url": "", "production_enabled": False},
    "official_verification": {"status": "OFFICIAL_VERIFICATION_PENDING"},
}

READY_CONFIG = {
    "environment": {
        "mode": "production", "api_version": "v24.0",
        "webhook_url": "https://example.com/webhook/whatsapp", "production_enabled": True,
    },
    "official_verification": {
        "status": "VERIFIED", "api_docs_verified": True,
        "account_configuration_verified": True, "business_verification_complete": True,
        "phone_number_configured": True, "webhook_reachable": True, "webhook_verified": True,
        "signature_tested": True, "outbound_tested": True, "template_requirements_satisfied": True,
        "optout_tested": True, "human_takeover_tested": True, "idempotency_tested": True,
        "outbox_tested": True, "policy_tested": True, "audit_tested": True,
        "health_pass": True, "owner_alert_configured": True, "secrets_configured": True,
    },
}

SECRETS = {
    "WHATSAPP_VERIFY_TOKEN": "t", "WHATSAPP_APP_SECRET": "s",
    "WHATSAPP_ACCESS_TOKEN": "a", "WHATSAPP_PHONE_NUMBER_ID": "p",
}


class ProductionGateTest(unittest.TestCase):
    def test_default_is_disabled(self):
        gate = ProductionGateService(MOCK_PRODUCTION_CONFIG)
        self.assertFalse(gate._production_enabled())
        report = gate.check()
        self.assertIn(report["verdict"], ("CONDITIONAL", "NOT_READY"))

    def test_not_ready_when_disabled_and_verified(self):
        gate = ProductionGateService(copy.deepcopy(READY_CONFIG), env=SECRETS)
        gate.config["environment"]["production_enabled"] = False
        report = gate.check()
        # even fully verified: disabled => never READY
        self.assertEqual(report["verdict"], "CONDITIONAL")
        self.assertFalse(report["production_enabled"])

    def test_not_ready_when_disabled_and_secrets_missing(self):
        gate = ProductionGateService(copy.deepcopy(READY_CONFIG), env={})
        gate.config["environment"]["production_enabled"] = False
        self.assertEqual(gate.check()["verdict"], "NOT_READY")

    def test_ready_only_when_enabled_and_verified(self):
        gate = ProductionGateService(copy.deepcopy(READY_CONFIG), env=SECRETS)
        report = gate.check()
        self.assertEqual(report["verdict"], "READY")

    def test_not_ready_when_enabled_but_verification_pending(self):
        cfg = {
            "environment": {"mode": "production", "production_enabled": True, "webhook_url": "https://x.io/w"},
            "official_verification": {"status": "OFFICIAL_VERIFICATION_PENDING"},
        }
        self.assertEqual(ProductionGateService(cfg).check()["verdict"], "NOT_READY")

    def test_secrets_presence(self):
        gate = ProductionGateService(MOCK_PRODUCTION_CONFIG, env={
            "WHATSAPP_VERIFY_TOKEN": "t", "WHATSAPP_APP_SECRET": "s",
            "WHATSAPP_ACCESS_TOKEN": "a", "WHATSAPP_PHONE_NUMBER_ID": "p",
        })
        self.assertTrue(gate._secrets_present())
        gate2 = ProductionGateService(MOCK_PRODUCTION_CONFIG, env={})
        self.assertFalse(gate2._secrets_present())

    def test_assert_send_allowed_blocks_when_disabled(self):
        gate = ProductionGateService(MOCK_PRODUCTION_CONFIG, env={
            "WHATSAPP_ACCESS_TOKEN": "secret-token-123", "WHATSAPP_PHONE_NUMBER_ID": "111",
        })
        with self.assertRaises(ProductionNotEnabledError):
            gate.assert_production_send_allowed()

    def test_assert_send_allowed_blocks_sandbox(self):
        cfg = {
            "environment": {"mode": "sandbox", "production_enabled": True, "webhook_url": ""},
            "official_verification": {},
        }
        with self.assertRaises(ProductionNotEnabledError):
            ProductionGateService(cfg).assert_production_send_allowed()

    def test_graph_provider_blocked_even_with_credentials(self):
        """Safety rule: credentials alone never unlock external sends."""
        provider = GraphWhatsAppProvider({
            "mode": "production",
            "production_enabled": False,
            "phone_number_id": "111",
            "base_url": "https://graph.facebook.com",
            "api_version": "v24.0",
        })
        provider.access_token = "EA-fake-token"
        with self.assertRaises(ProductionNotEnabledError):
            provider.send("5511", "text", "hello")

    def test_adapter_mock_mode_sends_without_gate(self):
        adapter = WhatsAppAdapter({"mode": "mock", "production_enabled": False})
        result = adapter.send("5511", "text", "hello")
        self.assertEqual(result["status"], "sent")


if __name__ == "__main__":
    unittest.main()
