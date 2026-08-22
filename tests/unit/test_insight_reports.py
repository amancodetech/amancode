import unittest

from amancore.analytics.service import AnalyticsService
from amancore.insights.memory import InsightMemory
from amancore.insights.model import new_insight, new_recommendation
from amancore.insights.reports import InsightReports
from tests.common import TempDirTestCase, make_db
from tests.insights_seed import seed_support_case, seed_won_deal


class InsightReportsTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.analytics = AnalyticsService(self.db)
        self.mem = InsightMemory(self.db)
        self.reports = InsightReports(self.db, self.analytics, self.mem)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _seed_insight(self, severity="HIGH", type_="anomaly"):
        insight, _ = self.mem.save_insight(new_insight(
            type_=type_, category="sales", title="T", summary="S",
            evidence={"metric": "m", "value": 1, "sample_size": 8},
            confidence="HIGH", severity=severity,
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="change_pricing", title="R",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="Review",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=True,
        )
        self.mem.save_recommendation(rec)
        return insight["insight_id"]

    def test_daily_brief_includes_high_severity(self):
        self._seed_insight(severity="HIGH")
        brief = self.reports.daily_brief()
        self.assertEqual(brief["period"], "daily")
        self.assertTrue(any(i["severity"] == "HIGH" for i in brief["important_changes"]))
        self.assertTrue(brief["pending_decisions"])

    def test_daily_brief_empty(self):
        brief = self.reports.daily_brief()
        self.assertEqual(brief["important_changes"], [])

    def test_weekly_review_shape(self):
        seed_won_deal(self.db, approved=1000, true_cost=400)
        self._seed_insight()
        review = self.reports.weekly_review()
        for key in ("acquisition", "sales", "pricing", "revenue", "content",
                    "support", "capacity", "ai", "insights", "recommendations"):
            self.assertIn(key, review)
        self.assertEqual(review["revenue"]["revenue"], 1000)

    def test_monthly_review_shape(self):
        seed_won_deal(self.db, approved=1000, true_cost=400)
        review = self.reports.monthly_review()
        for key in ("revenue", "gross_margin", "mrr", "acquisition", "growth_risks",
                    "product_opportunities", "data_quality"):
            self.assertIn(key, review)

    def test_critical_support_listed(self):
        seed_support_case(self.db, priority="CRITICAL", status="open")
        brief = self.reports.daily_brief()
        self.assertEqual(len(brief["critical_support"]), 1)


if __name__ == "__main__":
    unittest.main()
