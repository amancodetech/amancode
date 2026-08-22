"""Optimization analyses — deterministic, read-only, no invented data.

Revenue · Offer · Sales · Content · Support · AI Cost · Capacity.
Each returns an analysis dict with evidence; insights are created upstream.
"""

from __future__ import annotations

import json


class OptimizationAnalyzer:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics

    # ---- Revenue --------------------------------------------------------
    def revenue_profile(self) -> dict:
        rows = self.db.execute(
            "SELECT o.service AS k, COUNT(DISTINCT o.opportunity_id) AS deals, "
            "COALESCE(SUM(p.approved_price),0) AS revenue "
            "FROM pricing_snapshots p "
            "JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            "WHERE o.stage IN ('won','closed_won') GROUP BY o.service ORDER BY revenue DESC"
        ).fetchall()
        return {
            "revenue": self.analytics.revenue()["value"],
            "true_cost": self.analytics.true_cost()["value"],
            "gross_margin": self.analytics.gross_margin()["value"],
            "avg_deal_value": self.analytics.avg_deal_value()["value"],
            "by_service": [dict(r) for r in rows],
            "by_market": self.analytics.revenue_attribution("source_channel"),
        }

    # ---- Offer ----------------------------------------------------------
    def offer_analysis(self) -> dict:
        """Offer selection → proposal → win; downgrade/upgrade; objections."""
        rows = self.db.execute(
            "SELECT o.service, o.offer_id, o.stage, l.lead_id, o.opportunity_id "
            "FROM opportunities o JOIN leads l ON l.lead_id = o.lead_id"
        ).fetchall()
        offers: dict[str, dict] = {}
        objections: dict[str, int] = {}
        for r in rows:
            key = r["service"] or "unknown"
            o = offers.setdefault(key, {"service": key, "count": 0, "proposals": 0, "won": 0})
            o["count"] += 1
            if self._has_proposal(r["opportunity_id"]):
                o["proposals"] += 1
            if r["stage"] in ("won", "closed_won"):
                o["won"] += 1
        conv = self.db.execute(
            "SELECT objections FROM conversations WHERE objections IS NOT NULL"
        ).fetchall()
        for r in conv:
            try:
                for obj in json.loads(r["objections"] or "[]"):
                    objections[obj] = objections.get(obj, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
        for o in offers.values():
            o["proposal_rate"] = round(o["proposals"] / o["count"], 4) if o["count"] else None
            o["win_rate"] = round(o["won"] / o["proposals"], 4) if o["proposals"] else None
        return {
            "offers": sorted(offers.values(), key=lambda x: -x["count"]),
            "objections": dict(sorted(objections.items(), key=lambda x: -x[1])),
        }

    def _has_proposal(self, opportunity_id: str) -> bool:
        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM proposals WHERE opportunity_id = ?", (opportunity_id,)
        ).fetchone()
        return (row["c"] or 0) > 0

    # ---- Sales ----------------------------------------------------------
    def sales_analysis(self) -> dict:
        funnel = self.analytics.funnel()
        steps = {s["stage"]: s["count"] for s in funnel["steps"]}
        conversions = {f"{c['from']}->{c['to']}": c["rate"] for c in funnel["conversions"]}
        return {
            "funnel": steps,
            "conversions": conversions,
            "close_rate": self.analytics.close_rate()["value"],
            "avg_sales_cycle_days": self.analytics.sales_cycle_days()["value"],
            "objections": self.offer_analysis()["objections"],
        }

    def lost_analysis(self) -> dict:
        """Lost reasons — UNKNOWN when the data is absent (never invented)."""
        rows = self.db.execute(
            "SELECT reason, COUNT(*) AS c FROM opportunities "
            "WHERE stage IN ('lost','closed_lost') GROUP BY reason"
        ).fetchall()
        reasons = {r["reason"] or "UNKNOWN": r["c"] for r in rows} or {"UNKNOWN": 0}
        return reasons

    # ---- Content --------------------------------------------------------
    def content_analysis(self) -> dict:
        """Content → conversation → lead → opportunity → revenue priority."""
        rows = self.db.execute(
            "SELECT content_id, topic, market, language, platform, status FROM content_items"
        ).fetchall()
        return {"content_count": len(rows), "items": [dict(r) for r in rows]}

    def content_attribution(self) -> dict:
        """Leads/opportunities/revenue attributed via source_content_id."""
        rows = self.db.execute(
            "SELECT source_content_id AS cid, COUNT(*) AS leads FROM leads "
            "WHERE source_content_id IS NOT NULL GROUP BY source_content_id"
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "content_id": r["cid"], "leads": r["leads"],
                "qualified": self._count_leads(r["cid"], "lead_stage IN ('qualified','hot')"),
                "opportunities": self._count_opps(r["cid"]),
                "revenue": self._revenue_for_content(r["cid"]),
            })
        return sorted(out, key=lambda x: -x["revenue"])

    def _count_leads(self, cid: str, cond: str) -> int:
        row = self.db.execute(
            f"SELECT COUNT(*) AS c FROM leads WHERE source_content_id = ? AND {cond}", (cid,)
        ).fetchone()
        return row["c"] or 0

    def _count_opps(self, cid: str) -> int:
        row = self.db.execute(
            "SELECT COUNT(DISTINCT o.opportunity_id) AS c FROM opportunities o "
            "JOIN leads l ON l.lead_id = o.lead_id WHERE l.source_content_id = ?", (cid,)
        ).fetchone()
        return row["c"] or 0

    def _revenue_for_content(self, cid: str) -> float:
        row = self.db.execute(
            "SELECT COALESCE(SUM(p.approved_price),0) AS c FROM pricing_snapshots p "
            "JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            "JOIN leads l ON l.lead_id = o.lead_id "
            "WHERE l.source_content_id = ? AND o.stage IN ('won','closed_won')", (cid,)
        ).fetchone()
        return round(row["c"] or 0, 2)

    # ---- Support --------------------------------------------------------
    def support_analysis(self) -> dict:
        rows = self.db.execute(
            "SELECT category, priority, status, summary, created_at, resolved_at "
            "FROM support_cases"
        ).fetchall()
        by_category: dict[str, int] = {}
        recurring: dict[str, int] = {}
        for r in rows:
            by_category[r["category"]] = by_category.get(r["category"], 0) + 1
            if r["status"] in ("open", "in_progress", "waiting_customer", "waiting_owner"):
                recurring[r["category"]] = recurring.get(r["category"], 0) + 1
        return {
            "by_category": by_category,
            "open_by_category": recurring,
            "escalations": self.analytics.support_escalations()["value"],
            "reopen_rate": self.analytics.reopen_rate()["value"],
            "avg_resolution_hours": self.analytics.avg_resolution_hours()["value"],
            "critical_open": sum(1 for r in rows if r["priority"] == "CRITICAL"
                                 and r["status"] in ("open", "in_progress", "waiting_owner")),
        }

    def recurring_issues(self, threshold: int = 3) -> list[dict]:
        """Support categories with N+ open/repeated cases (product-improvement signal)."""
        rows = self.db.execute(
            "SELECT category, summary FROM support_cases WHERE status IN "
            "('open','in_progress','waiting_customer','waiting_owner')"
        ).fetchall()
        seen: dict[str, dict] = {}
        for r in rows:
            c = r["category"]
            entry = seen.setdefault(c, {"category": c, "count": 0, "examples": []})
            entry["count"] += 1
            if len(entry["examples"]) < 3 and r["summary"]:
                entry["examples"].append(r["summary"][:120])
        return [v for v in seen.values() if v["count"] >= threshold]

    # ---- AI cost --------------------------------------------------------
    def ai_cost_analysis(self) -> dict:
        usage = self.analytics.ai_usage_by("model")
        groups = usage["value"] or []
        pro_cost = sum(g["cost"] for g in groups if "pro" in (g["group"] or "").lower())
        flash_cost = sum(g["cost"] for g in groups if "flash" in (g["group"] or "").lower())
        total = sum(g["cost"] for g in groups)
        return {
            "total_cost": total,
            "by_model": groups,
            "pro_share": round(pro_cost / total, 4) if total else None,
            "flash_share": round(flash_cost / total, 4) if total else None,
            "cost_per_lead": self._cost_per_lead(total),
            "failure_rate": self.analytics.ai_failure_rate()["value"],
        }

    def _cost_per_lead(self, total_cost: float) -> float | None:
        leads = self.analytics.leads_total()["value"] or 0
        return round(total_cost / leads, 4) if leads else None

    # ---- Capacity -------------------------------------------------------
    def capacity_analysis(self) -> dict:
        projects = self.db.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(hours_logged),0) AS hours FROM projects "
            "WHERE status = 'active'"
        ).fetchone()
        month_start = self.analytics.baseline or ""
        return {
            "active_projects": projects["c"] or 0,
            "hours_logged": round(projects["hours"] or 0, 2),
            "projects_created_this_month": self._projects_this_month(),
        }

    def _projects_this_month(self) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM projects WHERE created_at >= datetime('now','start of month')"
        ).fetchone()
        return row["c"] or 0
