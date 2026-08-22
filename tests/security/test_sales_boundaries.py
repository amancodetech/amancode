import unittest

from amancore.agents.sales import SalesAgent


class SalesBoundaryTest(unittest.TestCase):
    def test_no_external_send(self):
        self.assertFalse(hasattr(SalesAgent, "send_message"))
        self.assertFalse(hasattr(SalesAgent, "publish"))
        self.assertFalse(hasattr(SalesAgent, "send_whatsapp"))

    def test_no_pricing_authority(self):
        self.assertFalse(hasattr(SalesAgent, "approve_final_price"))
        self.assertFalse(hasattr(SalesAgent, "calculate_price"))
        self.assertFalse(hasattr(SalesAgent, "approve_discount"))

    def test_no_business_brain_write(self):
        self.assertFalse(hasattr(SalesAgent, "write_business_brain"))

    def test_no_contract_or_refund(self):
        self.assertFalse(hasattr(SalesAgent, "sign_contract"))
        self.assertFalse(hasattr(SalesAgent, "issue_refund"))


if __name__ == "__main__":
    unittest.main()
