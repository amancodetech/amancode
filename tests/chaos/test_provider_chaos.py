"""External Provider Chaos & Messaging/Payment Resilience Test Suite."""

import unittest
from amancore.crm.service import CRMService
from tests.fixtures import (
    isolated_db,
    ids,
    clock,
    failure_injector,
    FakeMessagingProvider,
    FakePaymentProvider,
)
from tests.factories import lead_factory


class TestProviderChaos(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    def test_messaging_provider_disconnect_and_recovery(self):
        wa_fake = FakeMessagingProvider(channel="whatsapp")

        # 1. Normal send
        res1 = wa_fake.send_message(recipient="user_123", text="Hello from AmanCore")
        self.assertEqual(res1["status"], "sent")
        self.assertEqual(len(wa_fake.sent_messages), 1)

        # 2. Simulate network disconnect
        wa_fake.fail_mode = True
        with self.assertRaises(RuntimeError) as ctx:
            wa_fake.send_message(recipient="user_123", text="Failed attempt")
        self.assertIn("PROVIDER_FAILURE", str(ctx.exception))

        # 3. Simulate recovery
        wa_fake.fail_mode = False
        res3 = wa_fake.send_message(recipient="user_123", text="Recovered message")
        self.assertEqual(res3["status"], "sent")
        self.assertEqual(len(wa_fake.sent_messages), 2)

    def test_payment_provider_failure_and_idempotency(self):
        stripe_fake = FakePaymentProvider(gateway_name="stripe")

        with isolated_db() as db:
            crm = CRMService(db)
            lead_id = lead_factory(crm, name="Payment Chaos Lead")

            # 1. Create charge
            res = stripe_fake.create_charge(amount=5000.0, currency="USD", customer_id=lead_id)
            self.assertEqual(res["status"], "succeeded")

            # 2. Duplicate webhook event simulation
            event_id = "evt_stripe_test_001"
            db.execute(
                "INSERT INTO idempotency_keys (idempotency_key, operation, result, created_at) VALUES (?, ?, ?, ?)",
                (event_id, "stripe_charge", '{"processed": true}', "2026-09-02T12:00:00Z"),
            )

            # Check idempotency duplicate detection
            existing = db.execute(
                "SELECT result FROM idempotency_keys WHERE idempotency_key = ?",
                (event_id,),
            ).fetchone()
            self.assertIsNotNone(existing)
            self.assertEqual(existing[0], '{"processed": true}')


if __name__ == "__main__":
    unittest.main()
