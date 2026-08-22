import unittest
from datetime import datetime, timezone

from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService


class FollowupTest(unittest.TestCase):
    def test_plan_first_followup_plus_2_days(self):
        engine = FollowupEngine()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        plan = engine.plan({"lead_id": "L1", "status": "qualified"}, attempt=1, now=now)
        self.assertEqual(plan["status"], "planned")
        self.assertIn("01-03", plan["scheduled_at"])  # +2 days

    def test_no_followup_for_won_or_optout(self):
        engine = FollowupEngine()
        self.assertIsNone(engine.plan({"lead_id": "L1", "status": "won"}))
        self.assertIsNone(engine.plan({"lead_id": "L1", "status": "new", "opt_out": 1}))

    def test_max_attempts(self):
        engine = FollowupEngine()
        self.assertIsNone(engine.plan({"lead_id": "L1", "status": "qualified"}, attempt=4))


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.svc = HandoffService()

    def test_detect_human(self):
        self.assertEqual(self.svc.detect("I want to talk to a human"), "human_requested")

    def test_detect_legal(self):
        self.assertEqual(self.svc.detect("This is a legal question"), "legal")

    def test_detect_angry(self):
        self.assertEqual(self.svc.detect("I am very angry about this"), "angry_customer")

    def test_request_returns_handoff(self):
        h = self.svc.request(
            {"lead_id": "L1"}, {"conversation_id": "C1", "summary": "s"},
            "human_requested", urgency="high", lead_score=50,
        )
        self.assertEqual(h["lead_id"], "L1")
        self.assertEqual(h["urgency"], "high")
        self.assertEqual(h["lead_score"], 50)


if __name__ == "__main__":
    unittest.main()
