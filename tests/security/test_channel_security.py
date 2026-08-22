import unittest

from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.channels.website import WebsiteLeadIntake


class ChannelBoundaryTest(unittest.TestCase):
    def test_adapter_has_no_business_logic(self):
        self.assertFalse(hasattr(WhatsAppAdapter, "calculate_price"))
        self.assertFalse(hasattr(WhatsAppAdapter, "approve_price"))
        self.assertFalse(hasattr(WhatsAppAdapter, "write_business_brain"))
        self.assertFalse(hasattr(WhatsAppAdapter, "process_message"))

    def test_coordinator_has_no_pricing_authority(self):
        self.assertFalse(hasattr(MessageCoordinator, "calculate_price"))
        self.assertFalse(hasattr(MessageCoordinator, "approve_final_price"))

    def test_website_intake_has_no_pricing_or_brain(self):
        self.assertFalse(hasattr(WebsiteLeadIntake, "calculate_price"))
        self.assertFalse(hasattr(WebsiteLeadIntake, "write_business_brain"))


if __name__ == "__main__":
    unittest.main()
