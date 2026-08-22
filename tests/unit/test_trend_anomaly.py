import unittest

from amancore.insights.trends import classify_series, detect
from amancore.insights.anomalies import is_anomaly, materialized_anomaly

TREND_CFG = {"minimum_periods": 2, "change_threshold": 0.15}
ANOM_CFG = {"zscore_threshold": 2.0, "min_periods": 3}


class TrendDetectorTest(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(detect([], TREND_CFG), (None, "INSUFFICIENT_DATA"))
        self.assertEqual(detect([5], TREND_CFG), (None, "INSUFFICIENT_DATA"))

    def test_rising(self):
        label, conf = detect([10, 12, 14, 18, 25, 30], TREND_CFG)
        self.assertEqual(label, "rising")
        self.assertIn(conf, ("HIGH", "MEDIUM"))

    def test_falling(self):
        label, _ = detect([30, 28, 22, 18, 12, 8], TREND_CFG)
        self.assertEqual(label, "falling")

    def test_stable(self):
        label, conf = detect([10, 10, 11, 10, 10, 10], TREND_CFG)
        self.assertEqual(label, "stable")

    def test_all_zero_stable(self):
        label, conf = detect([0, 0, 0, 0], TREND_CFG)
        self.assertEqual(label, "stable")
        self.assertEqual(conf, "HIGH")

    def test_volatile(self):
        label, _ = detect([1, 20, 1, 20, 1, 20], TREND_CFG)
        self.assertEqual(label, "volatile")

    def test_emerging(self):
        label, _ = detect([0, 0, 0, 0, 1, 3], TREND_CFG)
        self.assertEqual(label, "emerging")

    def test_classify_series_shape(self):
        r = classify_series([1, 2, 3], TREND_CFG)
        self.assertIn("trend", r)
        self.assertIn("change_pct", r)
        self.assertIn("latest", r)
        self.assertEqual(r["latest"], 3)


class AnomalyDetectorTest(unittest.TestCase):
    def test_insufficient_history(self):
        flagged, z = is_anomaly(10, [1, 2], ANOM_CFG)
        self.assertFalse(flagged)
        self.assertIsNone(z)

    def test_detects_outlier(self):
        flagged, z = is_anomaly(100, [10, 12, 11, 13, 10, 12], ANOM_CFG)
        self.assertTrue(flagged)
        self.assertGreater(abs(z), 2.0)

    def test_no_anomaly_for_normal(self):
        flagged, _ = is_anomaly(11, [10, 12, 11, 13, 10, 12], ANOM_CFG)
        self.assertFalse(flagged)

    def test_materiality_direction(self):
        r = materialized_anomaly(metric="leads", value=2, history=[10, 12, 11, 13, 10, 12],
                                 config=ANOM_CFG, direction="low")
        self.assertIsNotNone(r)
        self.assertEqual(r["metric"], "leads")
        r2 = materialized_anomaly(metric="leads", value=2, history=[10, 12, 11, 13, 10, 12],
                                  config=ANOM_CFG, direction="high")
        self.assertIsNone(r2)

    def test_not_anomaly_within_threshold(self):
        r = materialized_anomaly(metric="x", value=13, history=[10, 12, 11, 13, 10, 12],
                                 config=ANOM_CFG)
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
