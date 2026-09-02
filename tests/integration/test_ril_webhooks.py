"""Integration Tests for External Webhook Boundary, Signatures & Replay Security."""

import hashlib
import hmac
import json
import time
import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    ChannelProjectResolver,
    RILIntegrationService,
    WebhookAdapter,
)
from tests.fixtures import isolated_db, ids, clock


class TestRILWebhooksIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_webhook_hmac_signature_validation(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            secret = "production_super_secret_webhook_key"
            adapter = WebhookAdapter(resolver, ril_service, secret_key=secret)

            payload = {
                "customer_id": "cust_partner_99",
                "name": "Partner Client",
                "message": "نحتاج نظام فواتير محاسبي وبوابة دفع وعملة SAR",
                "event_id": "evt_hook_001",
            }

            now_str = str(time.time())

            # 1. Valid signature
            valid_sig = hmac.new(
                secret.encode("utf-8"),
                json.dumps(payload, sort_keys=True).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            headers_valid = {"X-Signature": valid_sig, "X-Timestamp": now_str}
            res_valid = adapter.handle_inbound(payload, headers=headers_valid)
            self.assertEqual(res_valid["status"], "success")
            self.assertGreaterEqual(res_valid["total_requirements_count"], 2)

            # 2. Invalid signature
            headers_invalid = {"X-Signature": "invalid_bad_sig", "X-Timestamp": now_str}
            res_invalid = adapter.handle_inbound(payload, headers=headers_invalid)
            self.assertEqual(res_invalid["status"], "error")
            self.assertIn("Invalid or unauthenticated", res_invalid["error"])

    def test_webhook_replay_protection_and_size_limits(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = WebhookAdapter(
                resolver,
                ril_service,
                replay_window_seconds=10,
                max_payload_bytes=200,
            )

            payload = {"customer_id": "cust_replay_01", "message": "متجر إلكتروني"}

            # Expired timestamp (20 seconds ago, limit 10)
            expired_time = str(time.time() - 20)
            res_expired = adapter.handle_inbound(payload, headers={"X-Timestamp": expired_time})
            self.assertEqual(res_expired["status"], "error")

            # Oversized payload
            large_payload = {"customer_id": "cust_large", "message": "X" * 300}
            res_large = adapter.handle_inbound(large_payload, headers={"X-Timestamp": str(time.time())})
            self.assertEqual(res_large["status"], "error")


if __name__ == "__main__":
    unittest.main()
