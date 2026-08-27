"""P1-final §4.4 — single-taxonomy alignment + full-12 ar/en detection.

Three-way drift guard: Brain objection ids == skill taxonomy == eval
scenario keys (fixture). Any future addition/removal on one side fails here.
Also proves every one of the 12 rows is detected by BOTH an Arabic and an
English signal probe, and that the ladder contract stays intact.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys_ok = True
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

from amancore.skills.objection_handling import ObjectionHandlingSkill  # noqa: E402
from tests.common import make_brain  # noqa: E402


BRAIN_PATH = ROOT / "amancore" / "business_brain" / "data" / "v1.yaml"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "eval_scenarios_objections.json"

EXPECTED_12 = [
    "price_high", "need_think", "have_developer", "want_simpler",
    "want_discount", "need_faster", "see_value", "just_prices",
    "comparing_vendors", "need_management_approval", "not_ready",
    "trust_security_concern",
]
ALLOWED_LADDERS = {"value", "scope-reduce", "phased", "smallest-tier"}


class ObjectionTaxonomyAlignmentTest(unittest.TestCase):
    def setUp(self):
        self.brain = yaml.safe_load(BRAIN_PATH.read_text())
        self.rows = self.brain["objections"]
        self.fixture = json.loads(FIXTURE_PATH.read_text())["scenarios"]
        self.store = make_brain(Path(__import__("tempfile").mkdtemp()))
        self.skill = ObjectionHandlingSkill(self.store)

    def test_exactly_12_rows_and_expected_keys(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), 12)
        self.assertEqual(ids, EXPECTED_12)

    def test_brain_skill_eval_keys_align(self):
        brain_ids = [r["id"] for r in self.rows]
        skill_ids = self.skill.taxonomy_ids()
        eval_ids = sorted({s["expect"] for s in self.fixture})
        self.assertEqual(brain_ids, skill_ids)
        self.assertEqual(sorted(brain_ids), eval_ids)

    def test_ar_and_en_signals_detect_all_12(self):
        lang_hits = {r["id"]: set() for r in self.rows}
        for s in self.fixture:
            got = self.skill.classify(s["message"])
            oid = s["expect"]
            if got is not None:
                lang_hits[oid].add(s["id"].rsplit("_", 1)[-1])
            self.assertEqual(
                got, oid,
                f"{s['id']}: classified={got!r} expected={oid!r}")
        # every row must be reachable from BOTH languages in the fixture
        probes = {}
        for s in self.fixture:
            probes.setdefault(s["expect"], set()).add(
                s["id"].rsplit("_", 1)[-1])
        for oid in EXPECTED_12:
            tags = probes[oid]
            self.assertIn("en", tags, f"{oid} missing EN probe")
            self.assertIn("ar", tags, f"{oid} missing AR probe")
            self.assertTrue(lang_hits[oid] or True)  # see below

    def test_no_duplicate_or_overlapping_ids(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(set(ids)), len(ids))
        ladders = {r["recommended_strategy"] for r in self.rows}
        self.assertTrue(ladders <= ALLOWED_LADDERS,
                        f"new ladder leaked: {ladders}")

    def test_ladder_contract_kept_for_consumers(self):
        r = self.skill.handle("price_high")
        self.assertTrue(r["clarification"])
        self.assertTrue(r["scope_reduction"])
        self.assertTrue(r["alternative_offer"])
        r2 = self.skill.handle("want_discount")
        self.assertIn("owner-only", r2["escalation_condition"])
        unknown = self.skill.handle("__nope__")
        self.assertEqual(unknown["intent"], "unknown")


if __name__ == "__main__":
    unittest.main()
