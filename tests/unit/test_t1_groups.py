"""D1-approved T1 2-group gate (CH-T1). Pure policy, no I/O."""

import unittest

from amancore.conversation.policy import ConversationPolicy


class T1GroupsTest(unittest.TestCase):
    def setUp(self):
        self.p = ConversationPolicy()

    def test_empty_or_category_only_no_t1(self):
        self.assertFalse(self.p.t1_min_scope({}))
        self.assertFalse(self.p.t1_min_scope({"problem": "stated"}))

    def test_single_fact_no_t1(self):
        # D1: one fact is never enough, even timeline/scope alone
        self.assertFalse(self.p.t1_min_scope({"timeline": "2 weeks"}))
        self.assertFalse(self.p.t1_min_scope({"scope": "restaurant site"}))
        self.assertFalse(self.p.t1_min_scope({"budget": "$5000"}))

    def test_two_facts_same_group_no_t1(self):
        # pages + page_count are both shape — still one group
        self.assertFalse(self.p.t1_min_scope({"pages": 8, "page_count": 8}))

    def test_shape_plus_scale_allows_t1(self):
        self.assertTrue(self.p.t1_min_scope({"scope": "shop", "timeline": "month"}))
        self.assertTrue(self.p.t1_min_scope({"pages": 8, "users": 50}))
        self.assertTrue(self.p.t1_min_scope({"booking": True, "budget": "$1k"}))

    def test_two_nongroups_without_shape_no_t1(self):
        # timeline + budget without any shape fact is not scope context
        self.assertFalse(self.p.t1_min_scope({"timeline": "month", "budget": "$1k"}))

    def test_unknown_accepted_counts_as_present(self):
        # D4: explicitly deferred dims count via unknown_accepted list
        self.assertTrue(self.p.t1_min_scope(
            {"scope": "shop"}, unknown_accepted=["timeline"]))
        self.assertFalse(self.p.t1_min_scope(
            {"timeline": "month"}, unknown_accepted=["budget"]))


if __name__ == "__main__":
    unittest.main()
