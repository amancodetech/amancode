import unittest

from amancore.pricing.engine import PricingEngine
from tests.common import TempDirTestCase, make_brain


class PricingEngineTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        self.engine = PricingEngine(
            self.store,
            payment_fee_profiles={"default": {"percentage_fee": 0.03, "fixed_fee": 0}},
            price_validity_days=14,
        )

    def _scope(self, service="business_website_system", market="indonesia", hours=20):
        return {"service": service, "market": market, "estimated_hours": hours, "risk_level": "medium", "scope": "restaurant website"}

    def test_price_relationships(self):
        r = self.engine.price(self._scope())
        self.assertGreaterEqual(r["target_price"], r["minimum_approved"])
        self.assertGreaterEqual(r["minimum_approved"], r["cost_floor"])
        self.assertGreater(r["target_price"], 0)
        self.assertEqual(r["currency"], "IDR")  # indonesia profile

    def test_market_multiplier(self):
        idr = self.engine.price(self._scope(market="indonesia"))
        gcc = self.engine.price(self._scope(market="gcc"))
        self.assertGreater(gcc["target_price"], idr["target_price"])
        self.assertEqual(gcc["market_multiplier"], 1.5)

    def test_service_markup_different(self):
        website = self.engine.price(self._scope(service="business_website_system"))
        erp = self.engine.price(self._scope(service="business_system_mini_erp", hours=120))
        self.assertGreater(erp["target_price"], website["target_price"])

    def test_unknown_service_warns(self):
        r = self.engine.price(self._scope(service="nope"))
        self.assertTrue(any("unknown service" in w for w in r["warnings"]))
        self.assertEqual(r["confidence"], "low")

    def test_unknown_market_warns(self):
        r = self.engine.price(self._scope(market="france"))
        self.assertTrue(any("unknown market" in w for w in r["warnings"]))

    def test_high_risk_increases_reserve(self):
        low = self.engine.price({**self._scope(), "risk_level": "low"})
        high = self.engine.price({**self._scope(), "risk_level": "high"})
        self.assertGreater(high["risk_reserve"], low["risk_reserve"])

    def test_no_hours_low_confidence(self):
        r = self.engine.price({**self._scope(), "estimated_hours": 0})
        self.assertEqual(r["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
