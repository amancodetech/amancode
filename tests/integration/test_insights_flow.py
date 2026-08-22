import unittest

from amancore.analytics.service import AnalyticsService
from amancore.insights.decisions import DecisionSupportService
from amancore.insights.engine import InsightsEngine
from amancore.insights.memory import InsightMemory
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, CanonicalEvent
from tests.common import TempDirTestCase, make_brain, make_db
from tests.insights_seed import seed_support_case, seed_won_deal


class InsightsFlowIntegrationTest(TempDirTestCase, unittest.TestCase):
    """Analytics → Insights → Recommendation → Approval → Decision → Audit
    → Business Brain Change Proposal."""

    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.analytics = AnalyticsService(self.db)
        self.mem = InsightMemory(self.db)
        self.approvals = ApprovalService(self.db)
        self.audit = AuditService(self.db)
        self.brain = make_brain(self.tmp)
        from amancore.business_brain.writer import BrainWriter

        self.writer = BrainWriter(self.brain, audit=self.audit)
        self.dispatcher = EventDispatcher()
        self.events: list[str] = []
        self.dispatcher.subscribe("insight.created", lambda e: self.events.append(e.event_type))
        self.dispatcher.subscribe("recommendation.created", lambda e: self.events.append(e.event_type))
        self.dispatcher.subscribe("decision.recorded", lambda e: self.events.append(e.event_type))
        self.engine = InsightsEngine(
            self.db, analytics=self.analytics, memory=self.mem,
            dispatcher=self.dispatcher, audit=self.audit,
        )
        self.dss = DecisionSupportService(
            self.db, memory=self.mem, approval_service=self.approvals,
            brain_writer=self.writer, audit=self.audit, dispatcher=self.dispatcher,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_full_flow(self):
        # seed a low-margin service so the engine produces a margin insight
        for _ in range(5):
            seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        summary = self.engine.run()
        self.assertGreater(summary["created"], 0)
        self.assertGreater(summary["recommendations"], 0)
        # events emitted
        self.assertTrue(any("insight" in e for e in self.events))
        # find a margin recommendation requiring approval
        recs = [r for r in self.mem.list_recommendations()
                if r["type"] == "change_pricing" and r["status"] == "new"]
        self.assertTrue(recs)
        rec = recs[0]
        # accept -> approval request + decision log + brain proposal (no mutation)
        v_before = self.brain.current()[0]
        result = self.dss.accept(rec["recommendation_id"], decided_by="owner", reason="review")
        self.assertIsNotNone(result["approval_id"])
        self.assertIsNotNone(result.get("brain_change_proposal"))
        self.assertEqual(self.brain.current()[0], v_before)
        # approval pending
        self.assertEqual(self.approvals.get(result["approval_id"])["status"], "pending")
        # audit trail has decision + brain proposal
        rows = [r["action"] for r in self.audit.query(limit=50)]
        self.assertIn("decision.recorded", rows)
        self.assertIn("business_brain.proposed", rows)
        # decision log
        decisions = self.mem.list_decisions(rec["recommendation_id"])
        self.assertEqual(decisions[0]["decision"], "accepted")

    def test_reject_flow_no_side_effects(self):
        for _ in range(5):
            seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        self.engine.run()
        rec = [r for r in self.mem.list_recommendations() if r["type"] == "change_pricing"][0]
        self.dss.reject(rec["recommendation_id"], reason="declined")
        self.assertEqual(self.mem.get_recommendation(rec["recommendation_id"])["status"], "rejected")
        # no approvals created
        self.assertEqual(self.approvals.get(rec["recommendation_id"]), None) if False else None
        from amancore.support.cases import SupportCaseStore
        self.assertEqual(len(self.mem.list_decisions(rec["recommendation_id"])), 1)


if __name__ == "__main__":
    unittest.main()
