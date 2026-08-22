import unittest

from amancore.insights.model import (
    build_evidence,
    confidence_from_samples,
    new_insight,
    new_recommendation,
    severity_for,
)

POLICY = {"minimum_samples": 3, "sample_high": 10, "sample_medium": 5,
          "confidence_threshold": 0.7, "materiality_threshold": 200}


class ConfidenceModelTest(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(confidence_from_samples(2, 0.9, POLICY), "INSUFFICIENT_DATA")
        self.assertEqual(confidence_from_samples(0, 0.9, POLICY), "INSUFFICIENT_DATA")

    def test_high(self):
        self.assertEqual(confidence_from_samples(12, 0.9, POLICY), "HIGH")

    def test_medium(self):
        self.assertEqual(confidence_from_samples(6, 0.5, POLICY), "MEDIUM")

    def test_low(self):
        self.assertEqual(confidence_from_samples(3, 0.2, POLICY), "LOW")
        self.assertEqual(confidence_from_samples(6, 0.2, POLICY), "LOW")

    def test_severity_by_materiality(self):
        self.assertEqual(severity_for("HIGH", 50, policy=POLICY), "LOW")
        self.assertEqual(severity_for("HIGH", 250, policy=POLICY), "MEDIUM")
        self.assertEqual(severity_for("HIGH", 900, policy=POLICY), "HIGH")
        self.assertEqual(severity_for("MEDIUM", 900, policy=POLICY), "HIGH")
        self.assertEqual(severity_for("INSUFFICIENT_DATA", 900, policy=POLICY), "LOW")

    def test_severity_risk(self):
        self.assertEqual(severity_for("HIGH", None, is_risk=True, policy=POLICY), "HIGH")
        self.assertEqual(severity_for("LOW", None, is_risk=True, policy=POLICY), "MEDIUM")

    def test_severity_critical(self):
        self.assertEqual(severity_for("LOW", 0, is_critical=True, policy=POLICY), "CRITICAL")


class ModelBuildersTest(unittest.TestCase):
    def test_evidence(self):
        ev = build_evidence(source="x", metric="leads", value=10, baseline=5,
                            comparison="higher", period="7d", sample_size=10)
        self.assertEqual(ev["source"], "x")
        self.assertEqual(ev["sample_size"], 10)
        self.assertEqual(ev["comparison"], "higher")

    def test_new_insight(self):
        i = new_insight(type_="trend", category="sales", title="T", summary="S",
                        evidence={"metric": "m"}, confidence="HIGH", severity="MEDIUM",
                        fingerprint="f1", related_entities=["e1"])
        self.assertEqual(i["status"], "new")
        self.assertIn("insight_id", i)
        self.assertIn("detected_at", i)

    def test_new_recommendation(self):
        r = new_recommendation(
            insight_id="i1", type_="change_pricing", title="R", problem="P",
            evidence_ids=["i1"], proposed_action="A", alternatives=["B"],
            expected_benefit="E", expected_risk="R", dependencies="D",
            confidence="HIGH", requires_owner_approval=True,
        )
        self.assertEqual(r["status"], "new")
        self.assertEqual(r["evidence"]["evidence_ids"], ["i1"])
        self.assertTrue(r["requires_owner_approval"])


if __name__ == "__main__":
    unittest.main()
