import unittest

from amancore.functions.pricing import (
    calculate_discount,
    calculate_minimum_approved,
    calculate_negotiation_range,
    calculate_payment_fee,
    calculate_target_price,
    calculate_true_cost,
    validate_pricing,
)


class CostModelTest(unittest.TestCase):
    def test_true_cost(self):
        c = calculate_true_cost(estimated_hours=20, shadow_rate=40)
        self.assertEqual(c["founder_cost"], 800)
        self.assertEqual(c["revision_reserve"], 120)
        self.assertEqual(c["risk_reserve"], 120)
        self.assertEqual(c["true_cost"], 1040)
        self.assertEqual(c["cost_floor"], c["true_cost"])

    def test_with_external_and_payment(self):
        c = calculate_true_cost(
            estimated_hours=20, shadow_rate=40, external_costs=100,
            infrastructure_costs=50, payment_fees=60,
        )
        self.assertGreater(c["true_cost"], 1040)

    def test_payment_fee(self):
        self.assertEqual(calculate_payment_fee(2000, {"percentage_fee": 0.03, "fixed_fee": 0.5}), 60.5)

    def test_target_and_minimum(self):
        base = calculate_target_price(1000, 1.5)
        self.assertEqual(base, 1500)
        self.assertEqual(calculate_minimum_approved(1000, 1.3), 1300)
        lo, hi = calculate_negotiation_range(1500, 1300)
        self.assertEqual((lo, hi), (1300, 1500))

    def test_discount_recorded(self):
        d = calculate_discount(1000, 800, "scope reduction", "removed booking")
        self.assertEqual(d["percentage"], 20.0)
        self.assertEqual(d["approver"], "owner")


class PricingValidationTest(unittest.TestCase):
    def test_negative_rejected(self):
        errors = validate_pricing(estimated_hours=-5)
        self.assertTrue(any("estimated_hours" in e for e in errors))

    def test_unknown_service_market(self):
        errors = validate_pricing(service="nope", known_services={"website"}, market="france", known_markets={"indonesia"})
        self.assertTrue(any("unknown service" in e for e in errors))
        self.assertTrue(any("unknown market" in e for e in errors))

    def test_min_above_target_rejected(self):
        errors = validate_pricing(minimum_approved=2000, target_price=1000)
        self.assertTrue(any("minimum_approved > target_price" in e for e in errors))

    def test_target_below_floor_rejected(self):
        errors = validate_pricing(target_price=500, cost_floor=1000)
        self.assertTrue(any("target_price < cost_floor" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
