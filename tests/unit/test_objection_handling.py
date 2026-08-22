import unittest

from amancore.skills.objection_handling import ObjectionHandlingSkill
from tests.common import TempDirTestCase, make_brain


class ObjectionTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        _, self.brain = self.store.current()
        self.skill = ObjectionHandlingSkill(self.store)

    def test_classify_price(self):
        self.assertEqual(self.skill.classify("this is too expensive"), "price_high")

    def test_classify_discount(self):
        self.assertEqual(self.skill.classify("can you give me a discount?"), "want_discount")

    def test_classify_none(self):
        self.assertIsNone(self.skill.classify("I want to grow my business online"))

    def test_handle_price_follows_golden_rule(self):
        r = self.skill.handle("price_high", self.brain)
        self.assertTrue(r["clarification"])
        self.assertTrue(r["scope_reduction"])
        self.assertTrue(r["alternative_offer"])


if __name__ == "__main__":
    unittest.main()
