import unittest

from amancore.agents.pricing import PricingOfferAgent


class PricingBoundaryTest(unittest.TestCase):
    def test_no_external_send(self):
        self.assertFalse(hasattr(PricingOfferAgent, "send_message"))
        self.assertFalse(hasattr(PricingOfferAgent, "publish"))
        self.assertFalse(hasattr(PricingOfferAgent, "send_proposal"))

    def test_no_policy_or_brain_write(self):
        self.assertFalse(hasattr(PricingOfferAgent, "change_pricing_policy"))
        self.assertFalse(hasattr(PricingOfferAgent, "write_business_brain"))

    def test_no_final_price_authority(self):
        self.assertFalse(hasattr(PricingOfferAgent, "approve_final_price"))
        self.assertFalse(hasattr(PricingOfferAgent, "approve_discount"))

    def test_no_contract_or_legal(self):
        self.assertFalse(hasattr(PricingOfferAgent, "sign_contract"))
        self.assertFalse(hasattr(PricingOfferAgent, "promise_legal"))


if __name__ == "__main__":
    unittest.main()
