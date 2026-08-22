import unittest

from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.services.events import EventDispatcher
from tests.common import TempDirTestCase, make_brain, make_db


class MessageOutboxTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.outbox = MessageOutbox(self.db, max_attempts=2, retry_backoff_seconds=1)
        self.adapter = WhatsAppAdapter({"mode": "mock"})
        self.policy = ChannelPolicyEngine(self.brain)
        self.dispatcher = EventDispatcher()
        self.worker = OutboxWorker(self.outbox, {"whatsapp": self.adapter}, self.policy, dispatcher=self.dispatcher)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_enqueue_and_send(self):
        mid = self.outbox.enqueue("whatsapp", "5511", "text", "hello", idempotency_key="k1")
        self.assertEqual(self.outbox.get(mid)["status"], "queued")
        results = self.worker.drain()
        self.assertEqual(results[0]["status"], "sent")
        self.assertEqual(self.outbox.get(mid)["status"], "sent")

    def test_idempotency_prevents_resend(self):
        self.outbox.enqueue("whatsapp", "5511", "text", "hi", idempotency_key="dup")
        self.worker.drain()
        self.assertTrue(self.outbox.has_success_for("dup"))

    def test_retry_then_dead(self):
        class FailingAdapter(WhatsAppAdapter):
            def send(self, recipient, message_type, payload):
                raise RuntimeError("provider down")

        worker = OutboxWorker(self.outbox, {"whatsapp": FailingAdapter({"mode": "mock"})}, self.policy)
        mid = self.outbox.enqueue("whatsapp", "5511", "text", "hi")
        # attempt 1 → failed → queued (retry)
        worker.process_one(self.outbox.get(mid))
        self.assertEqual(self.outbox.get(mid)["status"], "queued")
        self.assertEqual(self.outbox.get(mid)["attempts"], 1)
        # attempt 2 → dead
        worker.process_one(self.outbox.get(mid))
        self.assertEqual(self.outbox.get(mid)["status"], "dead")

    def test_policy_deny_cancels(self):
        class DenyPolicy:
            def evaluate_send(self, channel, message_type, risk_level=""):
                return "deny"

        worker = OutboxWorker(self.outbox, {"whatsapp": self.adapter}, DenyPolicy())
        mid = self.outbox.enqueue("whatsapp", "5511", "text", "hi")
        results = worker.drain()
        self.assertEqual(results[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
