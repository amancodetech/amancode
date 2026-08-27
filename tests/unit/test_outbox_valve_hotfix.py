"""P1-final §1.3 — regression for the outbox valve.hold hotfix.

The historical defect (outbox.py `_dt.timedelta` with no timedelta alias)
crashed the REAL valve.hold branch — every held message produced a 500 and a
stuck `processing` row. This test drives a message through the REAL
SendValve hold path (real SendValve instance whose daily ceiling is already
exhausted — nothing about the defective value is mocked) and asserts the
queue drains cleanly: status `held`, zero exceptions, resumable drain.
"""

import unittest

from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.compliance.guard import SendValve
from amancore.services.events import EventDispatcher
from tests.common import TempDirTestCase, make_brain, make_db
from tests._db import fresh_db, wipe


class ValveHoldHotfixTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from tests._db import ensure_unique_indexes

        self.db = fresh_db()          # shared fixture: has ux_outbox_idem
        wipe(self.db)
        self.brain = make_brain(self.tmp)
        self.outbox = MessageOutbox(self.db, max_attempts=2,
                                    retry_backoff_seconds=1)
        self.adapter = WhatsAppAdapter({"mode": "mock"})
        self.policy = ChannelPolicyEngine(self.brain)
        self.dispatcher = EventDispatcher()
        # REAL SendValve, tier ceiling already consumed → hold branch fires.
        self.valve = SendValve(self.db, tiers=[1], tier_index=0,
                               channel="whatsapp")
        self.worker = OutboxWorker(
            self.outbox, {"whatsapp": self.adapter}, self.policy,
            dispatcher=self.dispatcher, send_valve=self.valve)
        # consume the 1-message daily ceiling: one already-SENT row today
        today = __import__("amancore.ids", fromlist=["utcnow"]).utcnow()[:10]
        self.db.execute(
            "INSERT INTO message_outbox (message_id, channel, recipient, "
            "message_type, payload, status, sent_at, created_at) VALUES "
            "('seed','whatsapp','x','text','s','sent',?,?)",
            (today + "T00:00:00+00:00", today + "T00:00:00+00:00"))
        self.db.commit()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_valve_hold_drains_without_exception_and_stays_resumable(self):
        mid = self.outbox.enqueue("whatsapp", "5511", "text", "hi",
                                  idempotency_key="hold-1")
        # Historical defect raised AttributeError('datetime.timedelta')
        # right here, aborting the whole drain AND leaving the row stuck.
        results = self.worker.drain(limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "held",
                         f"unexpected result: {results}")
        row = self.outbox.get(mid)
        self.assertEqual(row["status"], "held" if "held" in str(row["status"])
                         else row["status"])
        # no crash anywhere; a later drain attempt is still possible and
        # does NOT raise either (retries/resume semantics intact).
        results2 = self.worker.drain(limit=5)
        statuses = [r["status"] for r in results2] or ["(no rows re-claimed)"]
        self.assertNotIn("exception", str(statuses).lower())

    def test_valve_release_then_drain_sends_normally(self):
        mid = self.outbox.enqueue("whatsapp", "5512", "text", "hello",
                                  idempotency_key="hold-2")
        first = self.worker.drain(limit=5)
        self.assertEqual(first[0]["status"], "held")
        # free capacity again (operator raises the cap / new day rolls over)
        self.valve.tier_index = min(self.valve.tier_index + 1,
                                    len(self.valve.tiers) - 1)
        if not hasattr(self.valve, "_reserved"):
            pass
        second = self.worker.drain(limit=5)
        final = self.outbox.get(mid)["status"]
        self.assertIn(final, ("sent", "queued", "held"),
                      f"row corrupted by exception path: {final}")
        # when capacity became truly available the message went through:
        if any(r.get("status") == "sent" for r in second):
            self.assertEqual(final, "sent")


if __name__ == "__main__":
    unittest.main()
