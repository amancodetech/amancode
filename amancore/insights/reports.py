"""Insight reports — Executive Daily Brief, Weekly Business Review,
Monthly Strategy Review. Read-only, JSON-friendly.
"""

from __future__ import annotations

from datetime import datetime, timezone


class InsightReports:
    def __init__(self, db, analytics, memory, optimizer=None):
        self.db = db
        self.analytics = analytics
        self.memory = memory
        from .optimizers import OptimizationAnalyzer

        self.optimizer = optimizer or OptimizationAnalyzer(db, analytics)

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _active_insights(self) -> list[dict]:
        return self.memory.list_insights(status=None, limit=100)

    def _active_recommendations(self) -> list[dict]:
        return self.memory.list_recommendations(status=None, limit=100)

    def daily_brief(self, date_str: str | None = None) -> dict:
        date_str = date_str or self._today()
        insights = self._active_insights()
        return {
            "period": "daily",
            "date": date_str,
            "important_changes": [
                {"id": i["insight_id"], "title": i["title"], "severity": i["severity"],
                 "confidence": i["confidence"]}
                for i in insights if i["severity"] in ("HIGH", "CRITICAL")
            ],
            "hot_opportunities": self._hot_opportunities(),
            "critical_support": self._critical_support(),
            "anomalies": [
                {"id": i["insight_id"], "title": i["title"]}
                for i in insights if i["type"] == "anomaly"
            ],
            "ai_cost": self.analytics.ai_cost()["value"],
            "pending_decisions": [
                {"id": r["recommendation_id"], "title": r["title"], "type": r["type"]}
                for r in self._active_recommendations()
                if r["status"] in ("new", "under_review") and r["requires_owner_approval"]
            ],
        }

    def weekly_review(self) -> dict:
        insights = self._active_insights()
        return {
            "period": "weekly",
            "week_start": self.analytics.baseline,
            "acquisition": {
                "new_leads": self.analytics.leads_total()["value"],
                "by_source": self.analytics.leads_by_source()["value"],
            },
            "sales": {
                "funnel": self.analytics.funnel(),
                "close_rate": self.analytics.close_rate()["value"],
                "avg_cycle_days": self.analytics.sales_cycle_days()["value"],
                "lost_reasons": self.optimizer.lost_analysis(),
            },
            "pricing": {
                "avg_deal_value": self.analytics.avg_deal_value()["value"],
                "objections": self.optimizer.offer_analysis()["objections"],
            },
            "revenue": {
                "revenue": self.analytics.revenue()["value"],
                "gross_margin": self.analytics.gross_margin()["value"],
                "mrr": self.analytics.mrr()["value"],
            },
            "content": self.optimizer.content_attribution(),
            "support": self.optimizer.support_analysis(),
            "capacity": self.optimizer.capacity_analysis(),
            "ai": self.optimizer.ai_cost_analysis(),
            "insights": [
                {"id": i["insight_id"], "type": i["type"], "title": i["title"],
                 "confidence": i["confidence"], "severity": i["severity"]}
                for i in insights
            ],
            "recommendations": [
                {"id": r["recommendation_id"], "type": r["type"], "title": r["title"],
                 "status": r["status"], "requires_owner_approval": r["requires_owner_approval"]}
                for r in self._active_recommendations()
            ],
        }

    def monthly_review(self) -> dict:
        return {
            "period": "monthly",
            "month_start": self.analytics.baseline,
            "revenue": self.analytics.revenue()["value"],
            "true_cost": self.analytics.true_cost()["value"],
            "gross_margin": self.analytics.gross_margin()["value"],
            "mrr": self.analytics.mrr()["value"],
            "recurring_revenue": self.analytics.care_plan_revenue()["value"],
            "acquisition": self.analytics.attribution("source_channel"),
            "revenue_by_market": self._revenue_by_market(),
            "revenue_by_service": self.optimizer.revenue_profile()["by_service"],
            "customer_patterns": self._customer_patterns(),
            "growth_risks": [
                {"id": i["insight_id"], "title": i["title"], "severity": i["severity"]}
                for i in self._active_insights() if i["severity"] in ("HIGH", "CRITICAL")
            ],
            "product_opportunities": [
                {"id": i["insight_id"], "title": i["title"]}
                for i in self._active_insights() if i["type"] == "saas_candidate"
            ],
            "data_quality": self._data_quality_issues(),
        }

    def _hot_opportunities(self) -> list[dict]:
        from .opportunity import OpportunityDetector

        det = OpportunityDetector(self.db, self.analytics)
        return [{"lead_id": h["lead_id"], "name": h.get("name"), "company": h.get("company"),
                 "score": h.get("lead_score")} for h in det.hot_leads_waiting()[:10]]

    def _critical_support(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT case_id, category, summary FROM support_cases "
            "WHERE priority = 'CRITICAL' AND status IN ('open','in_progress','waiting_owner')"
        ).fetchall()
        return [dict(r) for r in rows]

    def _revenue_by_market(self) -> list[dict]:
        from .segments import SegmentAnalyzer

        return SegmentAnalyzer(self.db, self.analytics).revenue_by("market")

    def _customer_patterns(self) -> dict:
        return {
            "total_customers": self.db.execute("SELECT COUNT(*) AS c FROM customers").fetchone()["c"],
            "active_care_plans": self.db.execute(
                "SELECT COUNT(*) AS c FROM care_plans WHERE status = 'active'"
            ).fetchone()["c"],
        }

    def _data_quality_issues(self) -> list[dict]:
        from .data_quality import DataQualityService

        return DataQualityService(self.db).run_checks()
