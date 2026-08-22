import unittest

from amancore.analytics.service import AnalyticsService
from amancore.insights.decisions import DecisionSupportService
from amancore.insights.engine import InsightsEngine
from amancore.insights.memory import InsightMemory
from amancore.insights.model import new_insight, new_recommendation
from amancore.services.approvals import ApprovalService
from tests.common import TempDirTestCase, make_brain, make_db


class InsightsSecurityTest(TempDirTestCase, unittest.TestCase):
    """Boundaries that must never be crossed (spec sections 42, 55, 57)."""

    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.analytics = AnalyticsService(self.db)
        self.mem = InsightMemory(self.db)
        self.brain = make_brain(self.tmp)
        self.engine = InsightsEngine(self.db, analytics=self.analytics)
        self.dss = DecisionSupportService(
            self.db, memory=self.mem, approval_service=ApprovalService(self.db),
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_engine_has_no_business_authority(self):
        for banned in ("change_price", "approve_price", "change_markup", "write_business_brain",
                       "send_message", "send", "publish_content", "activate_production",
                       "change_policy", "change_offer", "change_market"):
            self.assertFalse(hasattr(self.engine, banned), banned)

    def test_engine_cannot_mutate_crm(self):
        for banned in ("create_lead", "update_lead", "create_opportunity", "won_opportunity",
                       "create_customer", "create_project"):
            self.assertFalse(hasattr(self.engine, banned), banned)

    def test_decision_service_has_no_auto_mutation(self):
        for banned in ("write_business_brain", "apply_pricing_change", "commit_brain"):
            self.assertFalse(hasattr(self.dss, banned), banned)

    def test_accept_does_not_mutate_brain(self):
        from amancore.business_brain.writer import BrainWriter

        writer = BrainWriter(self.brain)
        dss = DecisionSupportService(
            self.db, memory=self.mem, approval_service=ApprovalService(self.db),
            brain_writer=writer,
        )
        insight, _ = self.mem.save_insight(new_insight(
            type_="margin", category="margin", title="T", summary="S",
            evidence={"metric": "m", "value": 0.1, "sample_size": 8},
            confidence="HIGH", severity="HIGH",
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="change_pricing", title="R",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="Review",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=True,
        )
        rid = self.mem.save_recommendation(rec)
        v_before = self.brain.current()[0]
        content_before = self.brain.current()[1]
        dss.accept(rid, decided_by="owner")
        self.assertEqual(self.brain.current()[0], v_before)
        self.assertEqual(self.brain.current()[1], content_before)
        # brain versions unchanged — only a pending proposal file was staged
        self.assertEqual(len(self.brain.versions()), 1)

    def test_recommendation_cannot_bypass_approval(self):
        insight, _ = self.mem.save_insight(new_insight(
            type_="margin", category="margin", title="T", summary="S",
            evidence={"metric": "m", "value": 0.1, "sample_size": 8},
            confidence="HIGH", severity="HIGH",
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="change_pricing", title="R",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="Review",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=True,
        )
        rid = self.mem.save_recommendation(rec)
        # accepting requires an approval service (no shortcut)
        dss = DecisionSupportService(self.db, memory=self.mem)
        with self.assertRaises(Exception):
            dss.accept(rid)

    def test_no_secrets_in_insights(self):
        import os

        os.environ["WHATSAPP_ACCESS_TOKEN"] = "INSIGHTS_SECRET_XYZ"
        try:
            self.engine.run()
            rows = self.mem.list_insights()
            for i in rows:
                self.assertNotIn("INSIGHTS_SECRET_XYZ", str(i))
            self.assertNotIn("WHATSAPP_ACCESS_TOKEN", str(self.engine.run()))
        finally:
            os.environ.pop("WHATSAPP_ACCESS_TOKEN", None)

    def test_insufficient_data_no_executive_recommendation(self):
        # only 2 leads — nothing executive
        self.engine.run()
        for r in self.mem.list_recommendations():
            self.assertNotIn(r["type"], ("change_pricing", "change_offer", "change_policy", "capacity"))


if __name__ == "__main__":
    unittest.main()
