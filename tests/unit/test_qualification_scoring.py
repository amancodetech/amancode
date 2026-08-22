import unittest

from amancore.functions.lead_scoring import NURTURE, QUALIFIED, HOT, category, score
from amancore.sales.qualification import QualificationEngine


class ScoringTest(unittest.TestCase):
    def test_category_thresholds(self):
        self.assertEqual(category(70), HOT)
        self.assertEqual(category(40), QUALIFIED)
        self.assertEqual(category(39), NURTURE)

    def test_full_qualification_scores_high(self):
        qual = {
            "budget": "$5000", "need": "need", "urgency": "high",
            "authority": "owner", "fit": {"overall_fit": "high"},
            "outcome": "increase orders", "clarity": "high", "engagement": 5,
        }
        r = score(qual)
        self.assertGreaterEqual(r["score"], 70)
        self.assertEqual(r["category"], HOT)
        self.assertEqual(r["confidence"], 1.0)

    def test_missing_data_lowers_score_and_confidence(self):
        qual = {
            "budget": None, "need": None, "urgency": "", "authority": None,
            "fit": {"overall_fit": "low"}, "outcome": None, "clarity": "low", "engagement": 0,
        }
        r = score(qual)
        self.assertLess(r["score"], 40)
        self.assertEqual(r["category"], NURTURE)
        self.assertLess(r["confidence"], 1.0)
        self.assertIn("budget", r["missing_information"])


class QualificationTest(unittest.TestCase):
    def setUp(self):
        self.engine = QualificationEngine()

    def test_not_ready_with_missing(self):
        mem = {"facts": {"problem": "stated"}}
        qual = self.engine.qualify(mem, {}, {"overall_fit": "medium"}, 2)
        self.assertFalse(qual["decision_readiness"])
        self.assertIn("budget", qual["missing_information"])

    def test_ready(self):
        mem = {"facts": {
            "problem": "x", "desired_outcome": "y", "authority": "owner",
            "budget": "$5000", "timeline": "2 weeks",
        }}
        qual = self.engine.qualify(mem, {}, {"overall_fit": "high"}, 3)
        self.assertTrue(qual["decision_readiness"])
        self.assertEqual(qual["clarity"], "high")


if __name__ == "__main__":
    unittest.main()
