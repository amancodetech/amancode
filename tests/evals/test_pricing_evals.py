import json
import unittest
from pathlib import Path

from amancore.agents.pricing import PricingOfferAgent
from amancore.crm.service import CRMService
from amancore.pricing.engine import PricingEngine
from amancore.pricing.negotiation import NegotiationEngine
from amancore.pricing.proposal import ProposalGenerator, ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.services.approvals import ApprovalService
from amancore.services.events import EventDispatcher
from tests.common import TempDirTestCase, make_brain, make_db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class PricingEval(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.approvals = ApprovalService(self.db)
        self.engine = PricingEngine(self.brain, payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}})
        self.agent = PricingOfferAgent(
            self.brain, self.crm, self.engine,
            NegotiationEngine(self.engine, self.dispatcher),
            PricingSnapshotStore(self.db),
            ProposalGenerator(self.brain),
            ProposalStore(self.db),
            approvals=self.approvals, dispatcher=self.dispatcher,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _run_scenario(self, sc):
        lid = self.crm.create_lead(company="Co", market=sc["market"], industry=sc.get("industry"))
        opp_id = self.crm.create_opportunity(lid, sc["service"], scope_summary=sc.get("scope_summary"))
        return self.agent.analyze_and_price(opp_id)

    def test_agent_pricing_scenarios(self):
        scenarios = json.loads((FIXTURES / "pricing_scenarios.json").read_text())["scenarios"]
        for sc in scenarios:
            result = self._run_scenario(sc)
            pr = result["pricing_result"]
            exp = sc["expect"]
            if "currency" in exp:
                self.assertEqual(pr["currency"], exp["currency"], sc["id"])
            self.assertTrue(result["approval_required"], sc["id"])
            if exp.get("warning"):
                self.assertTrue(pr["warnings"], sc["id"])
            else:
                self.assertGreater(pr["target_price"], 0, sc["id"])

    def test_price_objection_reduces_scope_first(self):
        scope = {"service": "business_website_system", "market": "indonesia", "estimated_hours": 20, "risk_level": "medium", "scope": "x", "included": ["a", "b", "c"], "optional_features": ["c"]}
        res = self.engine.price(scope)
        out = NegotiationEngine(self.engine).on_price_objection(scope, res)
        self.assertTrue(out["price_moved"])
        self.assertEqual(out["discount"]["reason"], "scope reduction")

    def test_no_arbitrary_discount_and_escalation(self):
        scope = {"service": "business_website_system", "market": "indonesia", "estimated_hours": 20, "risk_level": "medium", "scope": "x", "included": ["a"], "optional_features": []}
        res = self.engine.price(scope)
        neg = NegotiationEngine(self.engine)
        out = neg.evaluate_budget(100, res)
        self.assertTrue(out["escalation"])  # below minimum → owner

    def test_snapshot_unchanged_after_rule_change(self):
        sc = {"service": "business_website_system", "market": "indonesia", "industry": "restaurant", "scope_summary": "restaurant website"}
        result = self._run_scenario(sc)
        self.approvals.approve(result["approval_id"], "owner")
        finalized = self.agent.finalize(result["approval_id"], "owner")
        sid = finalized["snapshot_id"]
        before = PricingSnapshotStore(self.db).get(sid)["approved_price"]
        # simulate brain/rule change: recompute with different scope
        scope2 = {"service": "business_system_mini_erp", "market": "gcc", "estimated_hours": 300, "risk_level": "critical", "scope": "big"}
        self.engine.price(scope2)
        after = PricingSnapshotStore(self.db).get(sid)["approved_price"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
