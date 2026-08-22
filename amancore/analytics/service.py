"""AnalyticsService — READ-ONLY KPI computation.

This service never mutates the database: every method is a SELECT. Security
tests enforce this (row counts unchanged after computing all KPIs).
All figures are deterministic; nothing is invented.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..storage.db import Database

WON_STAGES = {"won", "closed_won"}
LOST_STAGES = {"lost", "closed_lost"}
ACTIVE_SUPPORT_STATUSES = ("open", "in_progress", "waiting_customer", "waiting_owner")


def _iso(date_str: str | None) -> str | None:
    """YYYY-MM-DD or ISO-8601 -> ISO-8601 UTC."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return date_str  # already ISO


def _add_days(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=days)).isoformat()


class AnalyticsService:
    def __init__(self, db: Database, config: dict | None = None, baseline: str | None = None):
        self.db = db
        self.config = config or {}
        self._baseline = baseline
        self._baseline_cached = baseline is not None

    @property
    def baseline(self) -> str | None:
        """System activation date = earliest record (lazy, cacheable)."""
        if not self._baseline_cached:
            self._baseline = self._detect_baseline()
            self._baseline_cached = True
        return self._baseline

    # ---- baseline (system activation) ---------------------------------
    def _detect_baseline(self) -> str | None:
        """Earliest record in the system = system activation date."""
        parts = [
            self.db.execute("SELECT MIN(created_at) AS m FROM leads").fetchone()["m"],
            self.db.execute("SELECT MIN(timestamp) AS m FROM events").fetchone()["m"],
            self.db.execute("SELECT MIN(created_at) AS m FROM usage_records").fetchone()["m"],
            self.db.execute("SELECT MIN(created_at) AS m FROM support_cases").fetchone()["m"],
        ]
        return min(p for p in parts if p) if any(parts) else None

    def _window(self, start: str | None, end: str | None) -> tuple[str | None, str | None]:
        """Resolve window; returns (start_iso, end_iso). None = unbounded."""
        return (_iso(start), _iso(end))

    def _before_baseline(self, start: str | None) -> bool:
        return bool(start and self.baseline and start < self.baseline[:10])

    def kpi(self, name: str, value, start=None, end=None) -> dict:
        """Wrap a KPI with baseline awareness."""
        if self._before_baseline(start):
            return {"name": name, "value": None, "not_available": True}
        return {"name": name, "value": value, "not_available": False}

    def _q(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def _scalar(self, sql: str, params: tuple = ()) -> float | int | None:
        row = self.db.execute(sql, params).fetchone()
        return row[0] if row else None

    # ---- Marketing ------------------------------------------------------
    def leads_total(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM leads WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("new_leads", n, start, end)

    def leads_by_source(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        rows = self._q(
            "SELECT source_channel AS source, COUNT(*) AS c FROM leads "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?) "
            "GROUP BY source_channel ORDER BY c DESC",
            (s, s, e, e),
        )
        return self.kpi("leads_by_source", {r["source"] or "unknown": r["c"] for r in rows}, start, end)

    def engaged_leads(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(DISTINCT lead_id) FROM conversations "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("engaged_leads", n, start, end)

    def content_pieces(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM content_items WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("content_pieces", n, start, end)

    # ---- Sales ----------------------------------------------------------
    def _stage_count(self, stage, start=None, end=None) -> int:
        s, e = self._window(start, end)
        return self._scalar(
            "SELECT COUNT(*) FROM leads WHERE lead_stage = ? "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (stage, s, s, e, e),
        ) or 0

    def qualified_leads(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM leads WHERE lead_stage IN ('qualified','hot') "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("qualified_leads", n, start, end)

    def hot_leads(self, start=None, end=None) -> dict:
        return self.kpi("hot_leads", self._stage_count("hot", start, end), start, end)

    def opportunities(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM opportunities WHERE stage NOT IN ('won','lost','closed_won','closed_lost') "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("opportunities", n, start, end)

    def won(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM opportunities WHERE stage IN ('won','closed_won') "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("won", n, start, end)

    def lost(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM opportunities WHERE stage IN ('lost','closed_lost') "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("lost", n, start, end)

    def proposals_approved(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM proposals WHERE status = 'approved' "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("proposals_approved", n, start, end)

    def close_rate(self, start=None, end=None) -> dict:
        won = self.won(start, end)["value"] or 0
        lost = self.lost(start, end)["value"] or 0
        rate = round(won / (won + lost), 4) if (won + lost) else None
        return self.kpi("close_rate", rate, start, end)

    def avg_deal_value(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT AVG(p.approved_price) FROM pricing_snapshots p "
            "JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            "WHERE o.stage IN ('won','closed_won') "
            "AND (? IS NULL OR p.created_at >= ?) AND (? IS NULL OR p.created_at < ?)",
            (s, s, e, e),
        )
        v = round(v, 2) if v is not None else None
        return self.kpi("avg_deal_value", v, start, end)

    def sales_cycle_days(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT AVG(julianday(o.updated_at) - julianday(l.created_at)) "
            "FROM opportunities o JOIN leads l ON l.lead_id = o.lead_id "
            "WHERE o.stage IN ('won','closed_won') "
            "AND (? IS NULL OR o.created_at >= ?) AND (? IS NULL OR o.created_at < ?)",
            (s, s, e, e),
        )
        v = round(v, 2) if v is not None else None
        return self.kpi("sales_cycle_days", v, start, end)

    # ---- Finance ---------------------------------------------------------
    def _won_snapshots(self, start=None, end=None) -> list[dict]:
        s, e = self._window(start, end)
        return self._q(
            "SELECT p.*, o.lead_id, o.service FROM pricing_snapshots p "
            "JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            "WHERE o.stage IN ('won','closed_won') "
            "AND (? IS NULL OR p.created_at >= ?) AND (? IS NULL OR p.created_at < ?)",
            (s, s, e, e),
        )

    def revenue(self, start=None, end=None) -> dict:
        total = sum((r.get("approved_price") or 0) for r in self._won_snapshots(start, end))
        return self.kpi("revenue", round(total, 2), start, end)

    def true_cost(self, start=None, end=None) -> dict:
        total = 0.0
        for r in self._won_snapshots(start, end):
            try:
                calc = json.loads(r.get("calculated_result") or "{}")
                total += float(calc.get("true_cost") or 0.0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return self.kpi("true_cost", round(total, 2), start, end)

    def gross_margin(self, start=None, end=None) -> dict:
        rev = self.revenue(start, end)["value"] or 0
        cost = self.true_cost(start, end)["value"] or 0
        margin = round((rev - cost) / rev, 4) if rev else None
        return self.kpi("gross_margin", margin, start, end)

    def mrr(self, start=None, end=None) -> dict:
        """Monthly recurring revenue from ACTIVE care plans (normalized)."""
        rows = self._q("SELECT * FROM care_plans WHERE status = 'active'")
        total = 0.0
        for r in rows:
            price = r.get("price") or 0
            cycle = (r.get("billing_cycle") or "monthly").lower()
            factor = {"monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12, "weekly": 4.345}.get(cycle, 1.0)
            total += price * factor
        return self.kpi("mrr", round(total, 2), start, end)

    def care_plan_revenue(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT COALESCE(SUM(price),0) FROM care_plans "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("care_plan_revenue", round(v or 0, 2), start, end)

    # ---- Operations ------------------------------------------------------
    def projects_total(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM projects WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("projects", n, start, end)

    def hours_logged(self, start=None, end=None) -> dict:
        v = self._scalar("SELECT COALESCE(SUM(hours_logged),0) FROM projects")
        return self.kpi("hours_logged", round(v or 0, 2), start, end)

    # ---- AI ---------------------------------------------------------------
    def ai_cost(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT COALESCE(SUM(estimated_cost),0) FROM usage_records "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("ai_cost", round(v or 0, 4), start, end)

    def ai_tokens(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT COALESCE(SUM(input_tokens + output_tokens),0) FROM usage_records "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("ai_tokens", v or 0, start, end)

    def ai_failure_rate(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        total = self._scalar(
            "SELECT COUNT(*) FROM usage_records WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        errors = self._scalar(
            "SELECT COUNT(*) FROM usage_records WHERE status = 'error' "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        rate = round(errors / total, 4) if total else None
        return self.kpi("ai_failure_rate", rate, start, end)

    def ai_usage_by(self, group_by: str = "model", start=None, end=None) -> dict:
        """Group usage by model | provider | task_class."""
        s, e = self._window(start, end)
        col = group_by if group_by in ("model", "provider", "task_class") else "model"
        rows = self._q(
            f"SELECT {col} AS g, COUNT(*) AS requests, SUM(estimated_cost) AS cost, "
            f"SUM(input_tokens + output_tokens) AS tokens, AVG(latency_ms) AS avg_latency "
            f"FROM usage_records WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?) "
            f"GROUP BY {col} ORDER BY cost DESC",
            (s, s, e, e),
        )
        out = []
        for r in rows:
            out.append({
                "group": r["g"], "requests": r["requests"], "cost": round(r["cost"] or 0, 4),
                "tokens": r["tokens"] or 0, "avg_latency_ms": round(r["avg_latency"] or 0, 1),
            })
        return self.kpi(f"ai_usage_by_{group_by}", out, start, end)

    # ---- Support ----------------------------------------------------------
    def support_cases(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM support_cases WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("support_cases", n, start, end)

    def support_open(self, start=None, end=None) -> dict:
        statuses = ", ".join(f"'{x}'" for x in ACTIVE_SUPPORT_STATUSES)
        s, e = self._window(start, end)
        n = self._scalar(
            f"SELECT COUNT(*) FROM support_cases WHERE status IN ({statuses}) "
            f"AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("support_open", n, start, end)

    def support_escalations(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        n = self._scalar(
            "SELECT COUNT(*) FROM support_cases WHERE escalated = 1 "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        return self.kpi("support_escalations", n, start, end)

    def avg_resolution_hours(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        v = self._scalar(
            "SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) FROM support_cases "
            "WHERE resolved_at IS NOT NULL "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        )
        v = round(v, 2) if v is not None else None
        return self.kpi("avg_resolution_hours", v, start, end)

    def reopen_rate(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        resolved = self._scalar(
            "SELECT COUNT(*) FROM support_cases WHERE resolved_at IS NOT NULL "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        reopened = self._scalar(
            "SELECT COUNT(*) FROM support_cases WHERE reopened_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        rate = round(reopened / resolved, 4) if resolved else None
        return self.kpi("reopen_rate", rate, start, end)

    # ---- Funnel -----------------------------------------------------------
    def funnel(self, start=None, end=None) -> dict:
        s, e = self._window(start, end)
        leads = self._scalar(
            "SELECT COUNT(*) FROM leads WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        engaged = self._scalar(
            "SELECT COUNT(DISTINCT lead_id) FROM conversations "
            "WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        qualified = self._scalar(
            "SELECT COUNT(*) FROM leads WHERE lead_stage IN ('qualified','hot') "
            "AND (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?)",
            (s, s, e, e),
        ) or 0
        opportunities = self._scalar(
            "SELECT COUNT(DISTINCT o.lead_id) FROM opportunities o "
            "WHERE (? IS NULL OR o.created_at >= ?) AND (? IS NULL OR o.created_at < ?)",
            (s, s, e, e),
        ) or 0
        proposals = self._scalar(
            "SELECT COUNT(DISTINCT o.lead_id) FROM proposals p "
            "JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            "WHERE p.status = 'approved' "
            "AND (? IS NULL OR p.created_at >= ?) AND (? IS NULL OR p.created_at < ?)",
            (s, s, e, e),
        ) or 0
        won = self._scalar(
            "SELECT COUNT(DISTINCT o.lead_id) FROM opportunities o "
            "WHERE o.stage IN ('won','closed_won') "
            "AND (? IS NULL OR o.created_at >= ?) AND (? IS NULL OR o.created_at < ?)",
            (s, s, e, e),
        ) or 0
        steps = [
            ("lead", leads), ("engaged", engaged), ("qualified", qualified),
            ("opportunity", opportunities), ("proposal", proposals), ("won", won),
        ]
        conversions = []
        for i in range(len(steps) - 1):
            a, b = steps[i][1], steps[i + 1][1]
            conversions.append({
                "from": steps[i][0], "to": steps[i + 1][0],
                "rate": round(b / a, 4) if a else None,
            })
        return {"steps": [{"stage": k, "count": v} for k, v in steps], "conversions": conversions}

    # ---- Attribution ------------------------------------------------------
    def attribution(self, by: str = "source_channel", start=None, end=None) -> dict:
        col = by if by in (
            "source_channel", "source_campaign", "source_content_id",
            "source_referral_id", "source_search_term",
        ) else "source_channel"
        s, e = self._window(start, end)
        rows = self._q(
            f"SELECT {col} AS k, COUNT(*) AS c FROM leads "
            f"WHERE (? IS NULL OR created_at >= ?) AND (? IS NULL OR created_at < ?) "
            f"GROUP BY {col} ORDER BY c DESC",
            (s, s, e, e),
        )
        return {r["k"] or "unknown": r["c"] for r in rows}

    def revenue_attribution(self, by: str = "source_channel", start=None, end=None) -> dict:
        """Revenue by acquisition source: lead -> opportunity -> approved snapshot (won)."""
        col = by if by in (
            "source_channel", "source_campaign", "source_content_id",
            "source_referral_id", "source_search_term",
        ) else "source_channel"
        s, e = self._window(start, end)
        rows = self._q(
            f"SELECT l.{col} AS k, COUNT(DISTINCT o.opportunity_id) AS deals, "
            f"COALESCE(SUM(p.approved_price),0) AS revenue "
            f"FROM opportunities o "
            f"JOIN leads l ON l.lead_id = o.lead_id "
            f"JOIN pricing_snapshots p ON p.opportunity_id = o.opportunity_id "
            f"WHERE o.stage IN ('won','closed_won') "
            f"AND (? IS NULL OR p.created_at >= ?) AND (? IS NULL OR p.created_at < ?) "
            f"GROUP BY l.{col} ORDER BY revenue DESC",
            (s, s, e, e),
        )
        return [
            {"source": r["k"] or "unknown", "deals": r["deals"], "revenue": round(r["revenue"], 2)}
            for r in rows
        ]

    # ---- Reports ----------------------------------------------------------
    def report_daily(self, date_str: str) -> dict:
        end = _add_days(date_str, 1)
        return {
            "period": "daily", "date": date_str,
            "new_leads": self.leads_total(date_str, end)["value"],
            "hot_leads": self.hot_leads(date_str, end)["value"],
            "open_opportunities": self.opportunities(date_str, end)["value"],
            "messages": self._scalar(
                "SELECT COUNT(*) FROM events WHERE event_type = 'whatsapp.message.received' "
                "AND timestamp >= ? AND timestamp < ?", (date_str, end),
            ),
            "support_cases": self.support_cases(date_str, end)["value"],
            "errors": self._scalar(
                "SELECT COUNT(*) FROM usage_records WHERE status = 'error' "
                "AND created_at >= ? AND created_at < ?", (date_str, end),
            ),
            "ai_cost": self.ai_cost(date_str, end)["value"],
        }

    def report_weekly(self, date_str: str) -> dict:
        end = _add_days(date_str, 7)
        return {
            "period": "weekly", "week_start": date_str,
            "funnel": self.funnel(date_str, end),
            "revenue": self.revenue(date_str, end)["value"],
            "gross_margin": self.gross_margin(date_str, end)["value"],
            "close_rate": self.close_rate(date_str, end)["value"],
            "channel_performance": self.revenue_attribution("source_channel", date_str, end),
            "content_pieces": self.content_pieces(date_str, end)["value"],
            "support_trends": {
                "created": self.support_cases(date_str, end)["value"],
                "escalations": self.support_escalations(date_str, end)["value"],
                "open": self.support_open(date_str, end)["value"],
            },
        }

    def report_monthly(self, date_str: str) -> dict:
        end = _add_days(date_str, 30)
        return {
            "period": "monthly", "month_start": date_str,
            "revenue": self.revenue(date_str, end)["value"],
            "true_cost": self.true_cost(date_str, end)["value"],
            "gross_margin": self.gross_margin(date_str, end)["value"],
            "mrr": self.mrr(date_str, end)["value"],
            "acquisition": self.attribution("source_channel", date_str, end),
            "ai_cost": self.ai_cost(date_str, end)["value"],
            "capacity": {
                "projects": self.projects_total(date_str, end)["value"],
                "hours_logged": self.hours_logged(date_str, end)["value"],
            },
            "retention": self._retention(),
        }

    def _retention(self) -> dict:
        total = self._scalar("SELECT COUNT(*) FROM customers") or 0
        active = self._scalar(
            "SELECT COUNT(DISTINCT customer_id) FROM care_plans WHERE status = 'active'"
        ) or 0
        return {"active_customers": active, "total_customers": total,
                "retention_rate": round(active / total, 4) if total else None}

    # ---- KPI catalog ------------------------------------------------------
    def kpi_catalog(self) -> list[dict]:
        kpis = self.config.get("kpis", {})
        return [
            {
                "name": k, "definition": v.get("definition"), "formula": v.get("formula"),
                "source": v.get("source"), "time_window": v.get("time_window"),
                "aggregation": v.get("aggregation"), "caveats": v.get("caveats"),
            }
            for k, v in kpis.items()
        ]
