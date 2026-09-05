"""D2-approved Gate-B+ (CH-GATEB). Pure gate, no I/O."""

import unittest

from amancore.conversation.policy import ConversationPolicy
from amancore.conversation.pricing_flow import QuoteFlow


class GateBPlusTest(unittest.TestCase):
    def setUp(self):
        self.p = ConversationPolicy()

    def test_empty_or_category_only(self):
        self.assertFalse(QuoteFlow.gate_b_ready(self.p, None, {})[0]
                         if isinstance(QuoteFlow.gate_b_ready(self.p, None, {}), tuple)
                         else QuoteFlow.gate_b_ready(self.p, None, {}))
        self.assertFalse(QuoteFlow.gate_b_ready(self.p, "website", {}))

    def test_old_two_fact_rule_now_insufficient(self):
        # D2: scope+timeline alone is NOT enough (connect + authority/budget required)
        self.assertFalse(QuoteFlow.gate_b_ready(
            self.p, "website", {"scope": "pages", "timeline": "next month"}))

    def test_full_gate_passes(self):
        facts = {"scope": "shop", "timeline": "month",
                 "integrations": "mada", "budget": "$5k"}
        self.assertTrue(QuoteFlow.gate_b_ready(self.p, "website", facts))

    def test_payments_or_languages_count_as_connect(self):
        self.assertTrue(QuoteFlow.gate_b_ready(
            self.p, "website", {"scope": "s", "users": 10,
                                "payments": True, "authority": "owner"}))
        self.assertTrue(QuoteFlow.gate_b_ready(
            self.p, "website", {"scope": "s", "timeline": "m",
                                "languages": "ar+en", "budget": "b"}))

    def test_unknown_accepted_covers_suggestible_dims(self):
        # D4: explicitly deferred budget/authority/connect count as present
        facts = {"scope": "s", "timeline": "m", "integrations": "x"}
        self.assertTrue(QuoteFlow.gate_b_ready(
            self.p, "website", facts, unknown_accepted=["budget"]))
        # ...but never shape/scale
        self.assertFalse(QuoteFlow.gate_b_ready(
            self.p, "website", {"timeline": "m", "integrations": "x",
                                "budget": "b"}, unknown_accepted=["scope"]))

    def test_missing_out_names_gaps_for_autosuggest(self):
        missing = []
        QuoteFlow.gate_b_ready(self.p, "website", {"scope": "s"},
                               missing_out=missing)
        self.assertIn("scale", missing)
        self.assertIn("connect", missing)
        self.assertIn("authority_or_budget", missing)


if __name__ == "__main__":
    unittest.main()
