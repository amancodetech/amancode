import json
import unittest

from amancore.analytics.service import AnalyticsService
from amancore.crm.service import CRMService
from amancore.pricing.snapshot import PricingSnapshotStore
from tests.common import TempDirTestCase, make_db


class AnalyticsServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.crm = CRMService(self.db)
        self.svc = AnalyticsService(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _won_deal(self, lead_id, service, approved, true_cost, source="whatsapp"):
        opp_id = self.crm.create_opportunity(lead_id, service, estimated_value=approved)
        PricingSnapshotStore(self.db).create(
            opp_id,
            {"currency": "USD", "true_cost": true_cost, "pricing_policy_version": "v1"},
            approved_price=approved, approved_by="owner", business_brain_version=1,
        )
        cust = self.crm.won_opportunity(opp_id, "Co")
        return opp_id, cust

    def test_baseline_detection(self):
        lead_id = self.crm.create_lead(source_channel="whatsapp")
        self.assertIsNotNone(self.svc.baseline)
        self.assertLessEqual(self.svc.baseline[:19], "2999-01-01")
        # KPI before baseline -> NOT_AVAILABLE
        k = self.svc.leads_total("2000-01-01", "2000-01-02")
        self.assertTrue(k["not_available"])
        self.assertIsNone(k["value"])
        # all-time window works
        self.assertEqual(self.svc.leads_total()["value"], 1)

    def test_leads_by_source_and_stages(self):
        self.crm.create_lead(source_channel="whatsapp")
        self.crm.create_lead(source_channel="website")
        self.crm.create_lead(source_channel="website")
        self.svc2 = AnalyticsService(self.db)
        src = self.svc2.leads_by_source()["value"]
        self.assertEqual(src.get("website"), 2)
        self.assertEqual(src.get("whatsapp"), 1)
        self.assertEqual(self.svc2.leads_total()["value"], 3)

    def test_funnel(self):
        l1 = self.crm.create_lead(source_channel="whatsapp")
        l2 = self.crm.create_lead(source_channel="website")
        self.crm.update_lead(l1, lead_stage="hot")
        self.crm.update_lead(l2, lead_stage="nurture")
        self.crm.append_conversation(l1, "whatsapp")
        opp1 = self.crm.create_opportunity(l1, "website_standard")
        self._won_deal(l1, "website_standard", 1500, 600)
        funnel = self.svc.funnel()
        steps = {s["stage"]: s["count"] for s in funnel["steps"]}
        self.assertEqual(steps["lead"], 2)
        self.assertEqual(steps["engaged"], 1)
        self.assertEqual(steps["qualified"], 1)
        self.assertEqual(steps["opportunity"], 1)
        self.assertEqual(steps["won"], 1)

    def test_revenue_cost_margin(self):
        l1 = self.crm.create_lead(source_channel="whatsapp")
        l2 = self.crm.create_lead(source_channel="website")
        self._won_deal(l1, "website_standard", 1500, 600)
        self._won_deal(l2, "web_app", 4000, 1600)
        self.assertEqual(self.svc.revenue()["value"], 5500)
        self.assertEqual(self.svc.true_cost()["value"], 2200)
        self.assertEqual(self.svc.gross_margin()["value"], 0.6)
        self.assertEqual(self.svc.avg_deal_value()["value"], 2750)
        self.assertEqual(self.svc.close_rate()["value"], 1.0)

    def test_revenue_attribution(self):
        l1 = self.crm.create_lead(source_channel="whatsapp")
        l2 = self.crm.create_lead(source_channel="website")
        self._won_deal(l1, "website_standard", 1500, 600)
        self._won_deal(l2, "web_app", 4000, 1600)
        attr = {r["source"]: r["revenue"] for r in self.svc.revenue_attribution()}
        self.assertEqual(attr.get("whatsapp"), 1500)
        self.assertEqual(attr.get("website"), 4000)

    def test_mrr(self):
        cid = self.crm.create_customer("Co")
        self.crm.create_care_plan(cid, "basic", billing_cycle="monthly", price=200, status="active")
        self.crm.create_care_plan(cid, "yearly", billing_cycle="yearly", price=2400, status="active")
        self.crm.create_care_plan(cid, "draft", billing_cycle="monthly", price=999, status="draft")
        self.assertEqual(self.svc.mrr()["value"], 400)  # 200 + 2400/12

    def test_ai_cost_and_usage(self):
        self._insert_usage("dummy", "glm-dummy-pro", "strategy", 1000, 500, 0.05, 200, "ok")
        self._insert_usage("dummy", "glm-dummy-flash", "routine", 500, 100, 0.01, 150, "ok")
        self._insert_usage("dummy", "glm-dummy-pro", "strategy", 100, 50, 0.005, 300, "error")
        self.assertAlmostEqual(self.svc.ai_cost()["value"], 0.065, places=4)
        self.assertEqual(self.svc.ai_tokens()["value"], 2250)
        self.assertAlmostEqual(self.svc.ai_failure_rate()["value"], 1 / 3, places=4)
        by_model = self.svc.ai_usage_by("model")["value"]
        pro = [g for g in by_model if g["group"] == "glm-dummy-pro"][0]
        self.assertEqual(pro["requests"], 2)

    def _insert_usage(self, provider, model, task, inp, out, cost, lat, status):
        from amancore.ids import utcnow

        self.db.execute(
            "INSERT INTO usage_records (request_id, provider, model, task_class, "
            "input_tokens, output_tokens, estimated_cost, latency_ms, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"req-{provider}-{task}-{model}-{inp}", provider, model, task,
             inp, out, cost, lat, status, utcnow()),
        )
        self.db.commit()

    def test_support_metrics(self):
        from amancore.support.cases import SupportCaseStore

        store = SupportCaseStore(self.db)
        c1 = store.create("billing", priority="HIGH")
        store.escalate(c1, owner="owner")
        c2 = store.create("feature_request", priority="LOW")
        store.set_status(c2, "resolved")
        c3 = store.create("legal", priority="CRITICAL")
        store.set_status(c3, "resolved")
        store.set_status(c3, "open")  # reopen
        self.assertEqual(self.svc.support_cases()["value"], 3)
        self.assertEqual(self.svc.support_escalations()["value"], 1)
        self.assertEqual(self.svc.support_open()["value"], 2)
        self.assertEqual(self.svc.avg_resolution_hours()["value"], 0.0)
        self.assertAlmostEqual(self.svc.reopen_rate()["value"], 0.5, places=4)

    def test_read_only_no_mutation(self):
        tables = ["leads", "conversations", "opportunities", "support_cases",
                  "usage_records", "care_plans", "proposals", "pricing_snapshots"]
        before = {t: self.db.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in tables}
        self.svc.funnel()
        self.svc.leads_total()
        self.svc.leads_by_source()
        self.svc.attribution()
        self.svc.revenue_attribution()
        self.svc.revenue()
        self.svc.true_cost()
        self.svc.gross_margin()
        self.svc.mrr()
        self.svc.ai_cost()
        self.svc.support_cases()
        self.svc.report_daily("2999-01-01")
        self.svc.report_weekly("2999-01-01")
        self.svc.report_monthly("2999-01-01")
        after = {t: self.db.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in tables}
        self.assertEqual(before, after)

    def test_reports(self):
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        l1 = self.crm.create_lead(source_channel="whatsapp")
        self._won_deal(l1, "website_standard", 1500, 600)
        daily = self.svc.report_daily(today)
        self.assertEqual(daily["new_leads"], 1)
        monthly = self.svc.report_monthly(today)
        self.assertEqual(monthly["revenue"], 1500)
        self.assertEqual(monthly["gross_margin"], 0.6)

    def test_kpi_catalog(self):
        from pathlib import Path

        import yaml

        cfg = yaml.safe_load(
            (Path(__file__).resolve().parent.parent.parent / "configs" / "analytics.yaml").read_text(encoding="utf-8")
        )
        svc = AnalyticsService(self.db, config=cfg)
        catalog = svc.kpi_catalog()
        self.assertTrue(len(catalog) > 10)
        names = {k["name"] for k in catalog}
        for required in ("new_leads", "revenue", "gross_margin", "mrr", "ai_cost", "support_cases"):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
