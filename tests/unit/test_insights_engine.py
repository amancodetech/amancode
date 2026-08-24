import unittest
from pathlib import Path

import yaml

from amancore.analytics.service import AnalyticsService
from amancore.insights.engine import InsightsEngine
from amancore.insights.memory import InsightMemory
from amancore.insights.optimizers import OptimizationAnalyzer
from amancore.insights.segments import SegmentAnalyzer
from tests.common import TempDirTestCase, make_db
from tests.insights_seed import (
    seed_content,
    seed_lead,
    seed_opportunity,
    seed_project,
    seed_snapshot,
    seed_support_case,
    seed_usage,
    seed_won_deal,
)

ROOT = Path(__file__).resolve().parent.parent.parent
INSIGHTS_CFG = yaml.safe_load((ROOT / "configs" / "insights.yaml").read_text(encoding="utf-8"))


class InsightsEngineTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.analytics = AnalyticsService(self.db)
        self.alerts = []
        self.engine = InsightsEngine(
            self.db, analytics=self.analytics, config=INSIGHTS_CFG,
            owner_alert=lambda lvl, msg, corr, **kw: self.alerts.append((lvl, msg)),
        )
        self.mem = InsightMemory(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_empty_db_no_fake_insights(self):
        summary = self.engine.run()
        self.assertEqual(summary["created"], 0)
        self.assertEqual(self.mem.list_insights(), [])

    def test_data_quality_insight(self):
        # won deal without revenue snapshot
        lead = seed_lead(self.db)
        seed_opportunity(self.db, lead, stage="won")
        summary = self.engine.run()
        dq = [i for i in self.mem.list_insights() if i["type"] == "data_quality"]
        self.assertTrue(any("won deal without revenue" in i["summary"] for i in dq))

    def test_low_margin_insight(self):
        seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)  # 10% margin
        summary = self.engine.run()
        margins = [i for i in self.mem.list_insights() if i["type"] == "margin"]
        self.assertTrue(any(i["segment"] == "web_app" for i in margins))

    def test_support_recurrence_insight(self):
        for _ in range(4):
            seed_support_case(self.db, category="technical_support")
        summary = self.engine.run()
        rec = [i for i in self.mem.list_insights() if i["type"] == "support_recurrence"]
        self.assertTrue(any("technical_support" in i["segment"] for i in rec))

    def test_ai_cost_pro_share_insight(self):
        for _ in range(6):
            seed_usage(self.db, model="deepseek-v4-pro", cost=0.5)
        seed_usage(self.db, model="deepseek-v4-flash", cost=0.1)
        summary = self.engine.run()
        ai = [i for i in self.mem.list_insights() if i["type"] == "ai_cost"]
        self.assertTrue(any("Pro" in i["title"] for i in ai))

    def test_content_outperforms_insight(self):
        seed_content(self.db, content_id="c-best")
        seed_content(self.db, content_id="c-other")
        # 4 leads attributed to c-best, 1 to c-other
        for _ in range(5):
            seed_lead(self.db, source="content", days_ago=1)
        rows = self.db.execute("SELECT lead_id FROM leads").fetchall()
        for i, r in enumerate(rows):
            self.db.execute(
                "UPDATE leads SET source_content_id = ? WHERE lead_id = ?",
                ("c-best" if i < 4 else "c-other", r["lead_id"]),
            )
        self.db.commit()
        summary = self.engine.run()
        content = [i for i in self.mem.list_insights() if i["type"] == "content"]
        self.assertTrue(any(i["segment"] == "c-best" for i in content))

    def test_capacity_bottleneck(self):
        for _ in range(6):
            seed_project(self.db, hours=80.0)
        summary = self.engine.run()
        cap = [i for i in self.mem.list_insights() if i["type"] == "capacity"]
        self.assertTrue(cap)

    def test_hot_lead_opportunity(self):
        seed_lead(self.db, stage="hot", score=80, days_ago=5)
        summary = self.engine.run()
        opp = [i for i in self.mem.list_insights() if i["type"] == "opportunity"]
        self.assertTrue(any("hot lead" in i["title"] for i in opp))

    def test_saas_candidate(self):
        for _ in range(3):
            seed_support_case(self.db, category="technical_support")
        summary = self.engine.run()
        saas = [i for i in self.mem.list_insights() if i["type"] == "saas_candidate"]
        self.assertTrue(saas)

    def test_insufficient_data_no_recommendation(self):
        # only 2 leads -> insufficient data -> no executive recommendation
        seed_lead(self.db, days_ago=1)
        seed_lead(self.db, days_ago=1)
        summary = self.engine.run()
        recs = self.mem.list_recommendations()
        for r in recs:
            self.assertNotEqual(r["type"], "change_pricing")

    def test_dedup_no_duplicate_on_second_run(self):
        seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        self.engine.run()
        first_count = len(self.mem.list_insights())
        self.engine.run()
        self.assertEqual(len(self.mem.list_insights()), first_count)

    def test_severity_alerts(self):
        for _ in range(5):
            seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        self.engine.run()
        self.assertTrue(any(lvl in ("high", "critical") for lvl, _ in self.alerts))


class OptimizerSegmentTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.analytics = AnalyticsService(self.db)
        self.opt = OptimizationAnalyzer(self.db, self.analytics)
        self.seg = SegmentAnalyzer(self.db, self.analytics)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_margin_by_service(self):
        seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        seed_won_deal(self.db, service="website_standard", approved=1000, true_cost=400)
        margins = {m["segment"]: m["gross_margin"] for m in self.seg.margin_by("service")}
        self.assertEqual(margins["web_app"], 0.1)
        self.assertEqual(margins["website_standard"], 0.6)

    def test_revenue_by_market(self):
        seed_won_deal(self.db, market="gcc", approved=1500, true_cost=600)
        seed_won_deal(self.db, market="indonesia", approved=800, true_cost=300)
        rev = {r["segment"]: r["revenue"] for r in self.seg.revenue_by("market")}
        self.assertEqual(rev["gcc"], 1500)
        self.assertEqual(rev["indonesia"], 800)

    def test_offer_analysis(self):
        lead = seed_lead(self.db)
        seed_opportunity(self.db, lead, service="web_app", stage="offer_recommended")
        analysis = self.opt.offer_analysis()
        self.assertTrue(any(o["service"] == "web_app" for o in analysis["offers"]))

    def test_lost_reasons_unknown_when_absent(self):
        reasons = self.opt.lost_analysis()
        self.assertIn("UNKNOWN", reasons)

    def test_support_analysis(self):
        seed_support_case(self.db, category="billing", priority="HIGH", status="waiting_owner")
        analysis = self.opt.support_analysis()
        self.assertEqual(analysis["by_category"].get("billing"), 1)

    def test_ai_cost_analysis(self):
        seed_usage(self.db, model="deepseek-v4-pro", cost=0.5)
        analysis = self.opt.ai_cost_analysis()
        self.assertGreater(analysis["total_cost"], 0)
        self.assertIsNotNone(analysis["pro_share"])

    def test_revenue_profile(self):
        seed_won_deal(self.db, approved=1000, true_cost=400)
        profile = self.opt.revenue_profile()
        self.assertEqual(profile["revenue"], 1000)
        self.assertEqual(profile["gross_margin"], 0.6)


if __name__ == "__main__":
    unittest.main()
