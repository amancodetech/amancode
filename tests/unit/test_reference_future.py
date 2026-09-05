"""D5 reference candidates + D6 future-scope routing (pure helpers)."""

import unittest

from amancore.business_brain.store import BrainStore
from amancore.channels.coordinator import (
    detect_future_items,
    detect_reference_candidates,
)
from tests.common import ROOT


class ReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.brain = BrainStore(ROOT / "amancore" / "business_brain").current()

    def test_airbnb_ar(self):
        out = detect_reference_candidates("أريد شيئًا مثل إير بي إن بي", self.brain)
        self.assertIn("airbnb", out)
        self.assertIn("booking", out["airbnb"])

    def test_noon_en(self):
        out = detect_reference_candidates("like Noon but for spare parts", self.brain)
        self.assertIn("noon", out)
        self.assertIn("ecommerce", out["noon"])

    def test_no_cue_no_candidate(self):
        self.assertEqual(detect_reference_candidates("أريد متجرًا", self.brain), {})
        self.assertEqual(detect_reference_candidates("", self.brain), {})

    def test_candidates_never_write_facts(self):
        # helper returns hypotheses only — caller must confirm first
        out = detect_reference_candidates("مثل أوبر", self.brain)
        self.assertIsInstance(out, dict)
        self.assertIn("booking", out.get("uber", []))


class FutureTest(unittest.TestCase):
    def test_mobile_later(self):
        self.assertIn("mobile_app",
                      detect_future_items("نريد تطبيق جوال لاحقًا في المرحلة الثانية"))

    def test_current_scope_not_future(self):
        self.assertEqual(detect_future_items("أريد تطبيق جوال الآن"), set())
        self.assertEqual(detect_future_items("أريد موقعًا"), set())


if __name__ == "__main__":
    unittest.main()
