import unittest

from amancore.agents.pricing import PricingOfferAgent
from amancore.crm.service import CRMService
from amancore.pricing.engine import PricingEngine
from amancore.pricing.negotiation import NegotiationEngine
from amancore.pricing.proposal import ProposalGenerator, ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher
from tests.common import TempDirTestCase, make_brain, make_db


class PricingFlowTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        self.approvals = ApprovalService(self.db, audit=self.audit)
        self.engine = PricingEngine(self.brain, payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}})
        self.agent = PricingOfferAgent(
            self.brain, self.crm,
            self.engine,
            NegotiationEngine(self.engine, self.dispatcher),
            PricingSnapshotStore(self.db),
            ProposalGenerator(self.brain),
            ProposalStore(self.db),
            approvals=self.approvals,
            audit=self.audit, dispatcher=self.dispatcher,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _opportunity(self):
        lid = self.crm.create_lead(company="Resto", market="indonesia", industry="restaurant")
        return self.crm.create_opportunity(
            lid, "business_website_system", scope_summary="restaurant website with booking", stage="offer_recommended"
        )

    def test_full_pricing_flow(self):
        opp_id = self._opportunity()
        result = self.agent.analyze_and_price(opp_id)
        pr = result["pricing_result"]
        self.assertGreaterEqual(pr["target_price"], pr["minimum_approved"])
        self.assertTrue(result["approval_required"])
        self.assertTrue(result["approval_id"])

        self.approvals.approve(result["approval_id"], "owner")
        finalized = self.agent.finalize(result["approval_id"], "owner")
        self.assertTrue(finalized["snapshot_id"])
        snapshot = finalized["pricing_result"]

        proposal = self.agent.draft_proposal(opp_id, finalized["snapshot_id"])
        self.assertEqual(proposal["status"], "review")
        self.assertTrue(proposal["proposal_id"])
        stored = ProposalStore(self.db).get(proposal["proposal_id"])
        self.assertEqual(len(stored["body"]), 15)

    def test_snapshot_survives_recompute(self):
        opp_id = self._opportunity()
        result = self.agent.analyze_and_price(opp_id)
        self.approvals.approve(result["approval_id"], "owner")
        finalized = self.agent.finalize(result["approval_id"], "owner")
        sid = finalized["snapshot_id"]
        before = PricingSnapshotStore(self.db).get(sid)["approved_price"]
        # recompute with a different scope — snapshot stays frozen
        opp = self.crm.get_opportunity(opp_id)
        scope = {"service": "business_system_mini_erp", "market": "gcc", "estimated_hours": 200, "risk_level": "high", "scope": "big"}
        self.engine.price(scope)
        after = PricingSnapshotStore(self.db).get(sid)["approved_price"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
