import unittest

from amancore.pricing.engine import PricingEngine
from amancore.pricing.negotiation import NegotiationEngine
from tests.common import TempDirTestCase, make_brain


class NegotiationTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        self.engine = PricingEngine(self.store, payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}})
        self.neg = NegotiationEngine(self.engine)

    def _scope(self):
        return {
            "service": "business_website_system", "market": "indonesia",
            "estimated_hours": 20, "risk_level": "medium", "scope": "x",
            "included": ["site", "whatsapp", "booking"],
            "optional_features": ["booking"],
        }

    def test_scope_reduction_first(self):
        res = self.engine.price(self._scope())
        out = self.neg.on_price_objection(self._scope(), res)
        self.assertTrue(out["price_moved"])
        self.assertLess(out["new_pricing"]["target_price"], res["target_price"])
        # discount is scope-driven, not arbitrary
        self.assertEqual(out["discount"]["reason"], "scope reduction")
        self.assertEqual(out["discount"]["approver"], "owner")

    def test_no_arbitrary_discount(self):
        # removing optional features is the only price driver
        scope = self._scope()
        res = self.engine.price(scope)
        out = self.neg.on_price_objection(scope, res)
        self.assertEqual(out["reduced_scope"]["reduced_features"], ["booking"])

    def test_budget_below_minimum_escalates(self):
        res = self.engine.price(self._scope())
        out = self.neg.evaluate_budget(100, res)
        self.assertTrue(out["escalation"])
        self.assertEqual(out["action"], "owner_approval")

    def test_budget_in_zone_negotiates(self):
        res = self.engine.price(self._scope())
        mid = (res["target_price"] + res["minimum_approved"]) / 2
        out = self.neg.evaluate_budget(mid, res)
        self.assertEqual(out["action"], "negotiate_within_zone")

    def test_budget_above_target_proceeds(self):
        res = self.engine.price(self._scope())
        out = self.neg.evaluate_budget(res["target_price"] + 1000, res)
        self.assertEqual(out["action"], "proceed")


if __name__ == "__main__":
    unittest.main()
