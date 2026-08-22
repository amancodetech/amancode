import unittest

from amancore.support.intent import IntentRouter

POLICY = {
    "priority": {
        "security_incident": "CRITICAL", "complaint": "HIGH", "billing_dispute": "HIGH",
        "technical_support": "MEDIUM", "project_status": "MEDIUM",
        "feature_request": "LOW", "general": "LOW",
    }
}


class IntentRouterTest(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()

    def test_domain_legal(self):
        self.assertEqual(self.router.classify_domain("I will take legal action against you"), "legal")

    def test_domain_complaint(self):
        self.assertEqual(self.router.classify_domain("I am furious, this is a complaint"), "complaint")

    def test_domain_billing(self):
        self.assertEqual(self.router.classify_domain("I want a refund"), "billing")

    def test_domain_support(self):
        self.assertEqual(self.router.classify_domain("my website has an error"), "support")
        self.assertEqual(self.router.classify_domain("how is my project?"), "support")

    def test_domain_sales(self):
        self.assertEqual(self.router.classify_domain("I want to buy a website"), "sales")
        self.assertEqual(self.router.classify_domain("what is the price?"), "sales")

    def test_domain_general(self):
        self.assertEqual(self.router.classify_domain("hello there"), "general")

    def test_domain_critical_security(self):
        self.assertTrue(self.router.is_critical("there is a data breach right now"))
        self.assertEqual(self.router.classify_domain("security incident!"), "support")

    def test_category_mapping(self):
        self.assertEqual(self.router.classify_category("what is the status of my project"), "project_status")
        self.assertEqual(self.router.classify_category("I want a refund"), "billing")
        self.assertEqual(self.router.classify_category("can you add a new feature"), "feature_request")
        self.assertEqual(self.router.classify_category("the site crashes, error 500"), "technical_support")
        self.assertEqual(self.router.classify_category("I am going to sue"), "legal")
        self.assertEqual(self.router.classify_category("hello"), "general")

    def test_priority_for(self):
        self.assertEqual(self.router.priority_for("complaint", POLICY), "HIGH")
        self.assertEqual(self.router.priority_for("feature_request", POLICY), "LOW")
        self.assertEqual(self.router.priority_for("unknown_category", POLICY), "LOW")


if __name__ == "__main__":
    unittest.main()
