import unittest

from amancore.sales.fit import compute_fit
from tests.common import TempDirTestCase, make_brain


class FitTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        _, self.brain = self.store.current()

    def test_supported_market_industry_high(self):
        fit = compute_fit(self.brain, {"market": "indonesia", "industry": "trading", "website": "a.co.id"})
        self.assertEqual(fit["market_fit"], "high")
        self.assertEqual(fit["industry_fit"], "high")
        self.assertEqual(fit["maturity_fit"], "high")
        self.assertEqual(fit["overall_fit"], "high")

    def test_unsupported_market_low(self):
        fit = compute_fit(self.brain, {"market": "france", "industry": "trading"})
        self.assertEqual(fit["market_fit"], "low")
        self.assertEqual(fit["overall_fit"], "low")

    def test_fit_is_separate_from_score(self):
        fit = compute_fit(self.brain, {"market": "indonesia"})
        self.assertNotIn("score", fit)


if __name__ == "__main__":
    unittest.main()
