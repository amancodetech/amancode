import unittest

from amancore.crm.service import CRMService
from amancore.pricing.engine import PricingEngine
from amancore.pricing.proposal import ProposalGenerator
from amancore.pricing.snapshot import PricingSnapshotStore
from tests.common import TempDirTestCase, make_brain, make_db


class SnapshotTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = PricingSnapshotStore(self.db)
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.engine = PricingEngine(self.brain, payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}})

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _opp(self) -> str:
        lid = self.crm.create_lead(company="Co", market="indonesia")
        return self.crm.create_opportunity(lid, "business_website_system", scope_summary="restaurant website")

    def test_snapshot_is_immutable(self):
        opp_id = self._opp()
        scope = {"service": "business_website_system", "market": "indonesia", "estimated_hours": 20, "risk_level": "medium", "scope": "x"}
        r = self.engine.price(scope)
        sid = self.store.create(opp_id, r, approved_price=r["target_price"], approved_by="owner", business_brain_version=1)
        snap = self.store.get(sid)
        self.assertEqual(snap["approved_price"], r["target_price"])
        # later recomputation must NOT change the snapshot
        scope2 = {**scope, "estimated_hours": 100}
        r2 = self.engine.price(scope2)
        self.assertNotEqual(r2["target_price"], snap["approved_price"])
        self.assertEqual(self.store.get(sid)["approved_price"], r["target_price"])


class ProposalTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.gen = ProposalGenerator(self.brain)
        self.engine = PricingEngine(self.brain, payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}})
        self.snapshot_store = PricingSnapshotStore(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _opp(self) -> str:
        lid = self.crm.create_lead(company="Co", market="indonesia")
        return self.crm.create_opportunity(lid, "business_website_system", scope_summary="restaurant website")

    def _snapshot(self):
        opp_id = self._opp()
        scope = {"service": "business_website_system", "market": "indonesia", "estimated_hours": 20, "risk_level": "medium", "scope": "x"}
        r = self.engine.price(scope)
        sid = self.snapshot_store.create(opp_id, r, approved_price=1000, approved_by="owner", business_brain_version=1)
        return self.snapshot_store.get(sid)

    def test_proposal_sections(self):
        snap = self._snapshot()
        prop = self.gen.generate(
            {"opportunity_id": "OPP1", "scope_summary": "restaurant website"},
            {"included": ["site"], "excluded": [], "deliverables": ["delivery"]},
            {"service_name": "Business Website System"},
            snap,
            timeline="2 weeks",
            terms={"payment_terms": "50/50"},
        )
        self.assertEqual(len(prop["body"]), 15)  # 14 sections + approved claims
        self.assertIn("1000", prop["body"]["Investment"])
        self.assertEqual(prop["body"]["Timeline"], "2 weeks")

    def test_proposal_uses_only_approved_claims(self):
        snap = self._snapshot()
        prop = self.gen.generate(
            {"opportunity_id": "OPP1", "scope_summary": "x"},
            {"included": ["site"], "excluded": [], "deliverables": []},
            {"service_name": "Website"},
            snap,
        )
        brain = self.brain.current()[1]
        rendered = self.gen.render(prop)
        for forbidden in brain.get("forbidden_claims", []):
            self.assertNotIn(forbidden, rendered)

    def test_missing_policy_marks_owner_required(self):
        prop = self.gen.generate(
            {"opportunity_id": "OPP1", "scope_summary": ""},
            {"included": [], "excluded": [], "deliverables": []},
            {"service_name": "Website"},
            {"approved_price": None, "calculated_result": {}, "currency": "USD"},
        )
        self.assertIn("OWNER_APPROVAL_REQUIRED", prop["body"]["Investment"])
        self.assertIn("OWNER_APPROVAL_REQUIRED", prop["body"]["Payment Terms"])


if __name__ == "__main__":
    unittest.main()
