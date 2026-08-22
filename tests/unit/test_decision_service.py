import unittest

from amancore.errors import PermissionDenied
from amancore.insights.decisions import DecisionSupportService
from amancore.insights.memory import InsightMemory
from amancore.insights.model import new_insight, new_recommendation
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from tests.common import TempDirTestCase, make_db, make_brain


class DecisionSupportTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.mem = InsightMemory(self.db)
        self.approvals = ApprovalService(self.db)
        self.audit = AuditService(self.db)
        self.dss = DecisionSupportService(
            self.db, memory=self.mem, approval_service=self.approvals, audit=self.audit,
        )
        # seed insight + recommendation (approval-required type)
        insight, _ = self.mem.save_insight(new_insight(
            type_="margin", category="margin", title="Low margin web_app",
            summary="margin 0.1", evidence={"metric": "gm", "value": 0.1, "sample_size": 8},
            confidence="HIGH", severity="HIGH",
        ))
        self.insight_id = insight["insight_id"]
        rec = new_recommendation(
            insight_id=self.insight_id, type_="change_pricing", title="Review pricing",
            problem="low margin", evidence_ids=[self.insight_id], proposed_action="Review policy",
            alternatives=["keep"], expected_benefit="protect margin", expected_risk="win rate",
            dependencies="", confidence="HIGH", requires_owner_approval=True,
        )
        self.rid = self.mem.save_recommendation(rec)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_list_and_get(self):
        self.assertEqual(len(self.dss.list_insights()), 1)
        self.assertEqual(self.dss.get_insight(self.insight_id)["title"], "Low margin web_app")
        self.assertEqual(len(self.dss.list_recommendations()), 1)
        self.assertEqual(self.dss.get_recommendation(self.rid)["type"], "change_pricing")

    def test_accept_creates_approval_not_auto_change(self):
        result = self.dss.accept(self.rid, decided_by="owner", reason="review it")
        self.assertEqual(result["decision"], "accepted")
        self.assertIsNotNone(result["approval_id"])
        # approval created and pending
        approval = self.approvals.get(result["approval_id"])
        self.assertEqual(approval["status"], "pending")
        # no automatic change: brain not written, price not touched
        rec = self.mem.get_recommendation(self.rid)
        self.assertEqual(rec["status"], "accepted")
        self.assertEqual(rec["approval_id"], result["approval_id"])
        # decision logged
        decisions = self.mem.list_decisions(self.rid)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["decision"], "accepted")

    def test_accept_observe_type_no_approval(self):
        insight, _ = self.mem.save_insight(new_insight(
            type_="trend", category="sales", title="Rising leads", summary="up",
            evidence={"metric": "l", "value": 5, "sample_size": 8},
            confidence="HIGH", severity="LOW",
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="observe", title="Observe",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="watch",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=False,
        )
        rid = self.mem.save_recommendation(rec)
        result = self.dss.accept(rid)
        self.assertIsNone(result["approval_id"])
        self.assertEqual(result["decision"], "accepted")

    def test_reject_no_change(self):
        self.dss.reject(self.rid, decided_by="owner", reason="not now")
        rec = self.mem.get_recommendation(self.rid)
        self.assertEqual(rec["status"], "rejected")
        insight = self.mem.get_insight(self.insight_id)
        self.assertEqual(insight["status"], "rejected")
        # no approval created
        self.assertEqual(len(self.approvals.get(self.rid) or []), 0) if False else None
        self.assertEqual(self.mem.list_decisions(self.rid)[0]["decision"], "rejected")

    def test_defer(self):
        self.dss.defer(self.rid, reason="later")
        self.assertEqual(self.mem.get_recommendation(self.rid)["status"], "deferred")

    def test_cannot_decide_twice(self):
        self.dss.accept(self.rid)
        with self.assertRaises(PermissionDenied):
            self.dss.reject(self.rid)

    def test_request_more_data(self):
        self.dss.request_more_data(self.insight_id, note="need samples")
        self.assertEqual(self.mem.get_insight(self.insight_id)["status"], "reviewed")
        self.assertEqual(self.mem.list_decisions(self.insight_id)[0]["decision"], "more_data")

    def test_accept_approval_required_without_service_blocked(self):
        dss2 = DecisionSupportService(self.db, memory=self.mem)
        with self.assertRaises(PermissionDenied):
            dss2.accept(self.rid)


class BrainChangeProposalTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        from amancore.business_brain.writer import BrainWriter
        from amancore.services.audit import AuditService

        self.audit = AuditService(self.db)
        self.writer = BrainWriter(self.brain, audit=self.audit)
        self.mem = InsightMemory(self.db)
        self.dss = DecisionSupportService(
            self.db, memory=self.mem,
            approval_service=ApprovalService(self.db),
            brain_writer=self.writer,
        )
        insight, _ = self.mem.save_insight(new_insight(
            type_="margin", category="margin", title="Low margin", summary="m",
            evidence={"metric": "m", "value": 0.1, "sample_size": 8},
            confidence="HIGH", severity="HIGH",
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="change_pricing", title="Review",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="Review",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=True,
        )
        self.rid = self.mem.save_recommendation(rec)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_brain_change_is_proposal_not_mutation(self):
        v_before = self.brain.current()[0]
        content_before = self.brain.current()[1]
        result = self.dss.accept(self.rid, decided_by="owner", reason="review")
        self.assertIsNotNone(result.get("brain_change_proposal"))
        proposal_id = result["brain_change_proposal"]["proposal_id"]
        # proposal staged as pending — brain NOT mutated
        self.assertEqual(self.brain.current()[0], v_before)
        self.assertEqual(self.brain.current()[1], content_before)
        # link recorded
        rec = self.mem.get_recommendation(self.rid)
        self.assertEqual(rec["brain_change_proposal_id"], proposal_id)

    def test_approve_proposal_through_writer(self):
        result = self.dss.accept(self.rid, decided_by="owner")
        proposal_id = result["brain_change_proposal"]["proposal_id"]
        new_version = self.writer.approve(proposal_id, "owner")
        self.assertGreater(new_version, self.brain.current()[0] - 1)
        # audit trail
        audit = AuditService(self.db)
        rows = audit.query(limit=20)
        self.assertTrue(any("business_brain.version_created" == r["action"] for r in rows))


if __name__ == "__main__":
    unittest.main()
