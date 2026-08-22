import unittest

from amancore.insights.model import new_insight
from amancore.insights.recommendations import RecommendationEngine


def _insight(type_="trend", confidence="HIGH", **kw):
    base = dict(
        insight_id=f"i-{type_}", type=type_, category="sales", title="T",
        summary="S", confidence=confidence, severity="MEDIUM",
        segment="web_app", metrics={"trend": "falling"},
        evidence={"metric": "m", "value": 1, "sample_size": 10},
    )
    base.update(kw)
    return base


class RecommendationEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = RecommendationEngine()

    def test_insufficient_data_observe_only(self):
        rec = self.engine.generate(_insight(confidence="INSUFFICIENT_DATA"))
        self.assertEqual(rec["type"], "observe")
        self.assertFalse(rec["requires_owner_approval"])
        self.assertIn("Insufficient data", rec["proposed_action"])

    def test_approval_required_types(self):
        for type_, conf in [("margin", "HIGH"), ("pricing", "HIGH"), ("offer", "HIGH"),
                            ("market", "HIGH"), ("capacity", "HIGH"), ("saas_candidate", "HIGH")]:
            rec = self.engine.generate(_insight(type_=type_, confidence=conf))
            self.assertTrue(rec["requires_owner_approval"], type_)

    def test_evidence_ids_present(self):
        for type_ in ("trend", "anomaly", "margin", "pricing", "offer", "content",
                      "support_recurrence", "ai_cost", "capacity", "saas_candidate", "data_quality"):
            rec = self.engine.generate(_insight(type_=type_))
            self.assertIn("i-" + type_, rec["evidence"]["evidence_ids"], type_)

    def test_quality_fields(self):
        rec = self.engine.generate(_insight(type_="margin"))
        for field in ("title", "problem", "proposed_action", "expected_benefit",
                      "expected_risk", "required_decision", "what_if_ignored"):
            self.assertTrue(rec.get(field), field)

    def test_margin_rec_is_review_not_repricing(self):
        rec = self.engine.generate(_insight(type_="margin"))
        self.assertIn("Review", rec["proposed_action"])
        self.assertNotIn("Raise price to", rec["proposed_action"])

    def test_capacity_rec_is_consideration_not_hiring(self):
        rec = self.engine.generate(_insight(type_="capacity"))
        self.assertIn("considered", rec["proposed_action"])
        self.assertNotIn("Hire", rec["proposed_action"])

    def test_saas_rec_is_evaluate_not_build(self):
        rec = self.engine.generate(_insight(type_="saas_candidate"))
        self.assertIn("do NOT build", rec["proposed_action"])

    def test_no_generic_recommendation(self):
        for type_ in ("margin", "pricing", "content", "support_recurrence", "ai_cost"):
            rec = self.engine.generate(_insight(type_=type_))
            self.assertNotIn("Improve marketing", rec["proposed_action"])
            self.assertNotIn("Improve marketing", rec["title"])


if __name__ == "__main__":
    unittest.main()
