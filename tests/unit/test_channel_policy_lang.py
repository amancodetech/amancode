import unittest

from amancore.channels.language import LanguageDetector
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from tests.common import TempDirTestCase, make_brain


class LanguageTest(unittest.TestCase):
    def test_detect(self):
        d = LanguageDetector()
        self.assertEqual(d.detect("مرحبا، أريد موقعا"), "ar")
        self.assertEqual(d.detect("saya mau pesan website"), "id")
        self.assertEqual(d.detect("I want a website please"), "en")


class ResponseFilterTest(unittest.TestCase):
    def test_blocks_internal_data(self):
        f = ExternalResponseFilter()
        self.assertTrue(f.check("Thanks for your interest!")["allowed"])
        blocked = f.check("Our true cost is 800 and shadow rate is 40")
        self.assertFalse(blocked["allowed"])
        self.assertIn("shadow rate", blocked["found"])

    def test_sanitize(self):
        f = ExternalResponseFilter()
        clean = f.sanitize("true_cost internal")
        self.assertNotIn("true_cost", clean)


class ChannelPolicyTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.policy = ChannelPolicyEngine(make_brain(self.tmp))

    def test_send_policy(self):
        self.assertEqual(self.policy.evaluate_send("whatsapp", "text"), "allow")
        self.assertEqual(self.policy.evaluate_send("whatsapp", "template"), "approval_required")
        self.assertEqual(self.policy.evaluate_send("whatsapp", "proposal"), "approval_required")
        self.assertEqual(self.policy.evaluate_send("whatsapp", "text", "critical"), "deny")


if __name__ == "__main__":
    unittest.main()
