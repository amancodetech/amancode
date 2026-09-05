"""D3-A tier derivation + D4 unknown-accepted capture (pure helpers)."""

import unittest

from amancore.channels.coordinator import detect_unknown_accepted
from amancore.pricing.registry import tier_for_category


class TierTest(unittest.TestCase):
    def test_known_categories(self):
        self.assertEqual(tier_for_category("website"), "website")
        self.assertEqual(tier_for_category("ecommerce"), "website")
        self.assertEqual(tier_for_category("mobile"), "mobile")
        self.assertEqual(tier_for_category("business_system"), "mini_erp")
        self.assertEqual(tier_for_category("automation"), "web_app")

    def test_fallback_is_legacy_website(self):
        self.assertEqual(tier_for_category(None), "website")
        self.assertEqual(tier_for_category("nope"), "website")


class UnknownAcceptedTest(unittest.TestCase):
    def test_budget_deferral(self):
        self.assertEqual(detect_unknown_accepted("لا أعرف الميزانية بعد"),
                         {"budget"})
        self.assertEqual(detect_unknown_accepted("not sure about budget, defer"),
                         {"budget"})

    def test_multi_dim(self):
        self.assertEqual(
            detect_unknown_accepted("اللغة والربط بعدين"),
            {"languages", "integrations"})

    def test_shape_scale_never_accepted(self):
        # no keywords for shape/scale exist — nothing to accept
        self.assertEqual(detect_unknown_accepted("لا أعرف"), set())
        self.assertEqual(detect_unknown_accepted("أريد موقع"), set())

    def test_no_cue_no_accept(self):
        self.assertEqual(detect_unknown_accepted("الميزانية 5000"), set())
        self.assertEqual(detect_unknown_accepted(""), set())
        self.assertEqual(detect_unknown_accepted(None), set())


if __name__ == "__main__":
    unittest.main()
