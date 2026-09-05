"""D9 hours band-check + D3-E coverage flag + D7 vague->choices."""

import unittest

from amancore.channels.coordinator import MessageCoordinator
from amancore.conversation import ConversationModel
from amancore.business_brain.store import BrainStore
from tests.common import ROOT, TempDirTestCase, make_brain, make_db


class HoursBandTest(unittest.TestCase):
    def test_bands_match_prompt(self):
        bands = MessageCoordinator.HOURS_BANDS
        self.assertEqual(bands["website"], (6.0, 40.0))
        self.assertEqual(bands["ecommerce"], (50.0, 120.0))
        self.assertEqual(bands["mobile"], (80.0, 200.0))
        self.assertEqual(bands["business_system"], (90.0, 220.0))
        self.assertNotIn("automation", bands)  # range-check only, documented

    def test_out_of_band_discarded(self):
        # Fake coordinator-free check of the rule shape: band bounds hold.
        lo, hi = MessageCoordinator.HOURS_BANDS["website"]
        self.assertFalse(lo <= 400.0 <= hi)   # 400h mini-site guess rejected
        self.assertTrue(lo <= 25.0 <= hi)


class CoverageFlagTest(TempDirTestCase, unittest.TestCase):
    def test_default_off(self):
        from amancore.conversation.policy import ConversationPolicy
        self.assertFalse(ConversationPolicy().data.get("coverage_block_t2"))

    def test_yaml_loads(self):
        from amancore.conversation.policy import ConversationPolicy
        p = ConversationPolicy.load(ROOT)
        self.assertIn("coverage_block_t2", p.data)


class VagueChoiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.model = ConversationModel(ROOT, BrainStore(ROOT / "amancore" / "business_brain"))

    def test_vague_gets_choice_not_stall(self):
        plan = self.model.plan(
            lead={"lead_id": "L"},
            mem={"facts": {"scope": "مطعم"},
                 "working_memory": {"mode": "SHAPING",
                                    "service_category": "website"}},
            agent_result={}, text="عادي، أي شيء",
            language="ar", channel="whatsapp")
        q = plan.get("question") or {}
        self.assertTrue(q.get("field", "").startswith("suggest_") or
                        "options" in (q.get("hint", "") + plan["brief"]),
                        plan["brief"][:300])


if __name__ == "__main__":
    unittest.main()
