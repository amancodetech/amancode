"""Segment analysis — market / service / source / customer-type (deterministic).

Segments are derived from ACTUAL data only (no invented industries/markets).
"""

from __future__ import annotations


class SegmentAnalyzer:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics

    def revenue_by(self, column: str) -> list[dict]:
        """Revenue + deals by service/market/source for WON deals (approved prices only)."""
        col = column if column in ("service", "market", "source_channel") else "service"
        join = {
            "service": "o.service",
            "market": "l.market",
            "source_channel": "l.source_channel",
        }[col]
        rows = self.db.execute(
            f"SELECT {join} AS segment, COUNT(DISTINCT o.opportunity_id) AS deals, "
            f"COALESCE(SUM(p.approved_price),0) AS revenue, "
            f"COALESCE(AVG(p.approved_price),0) AS avg_deal "
            f"FROM pricing_snapshots p "
            f"JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            f"JOIN leads l ON l.lead_id = o.lead_id "
            f"WHERE o.stage IN ('won','closed_won') GROUP BY {join} ORDER BY revenue DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def margin_by(self, column: str) -> list[dict]:
        """Gross margin per segment: (revenue - true_cost)/revenue from won snapshots."""
        col = column if column in ("service", "market", "source_channel") else "service"
        join = {
            "service": "o.service",
            "market": "l.market",
            "source_channel": "l.source_channel",
        }[col]
        rows = self.db.execute(
            f"SELECT {join} AS segment, COUNT(DISTINCT o.opportunity_id) AS deals, "
            f"COALESCE(SUM(p.approved_price),0) AS revenue "
            f"FROM pricing_snapshots p "
            f"JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            f"JOIN leads l ON l.lead_id = o.lead_id "
            f"WHERE o.stage IN ('won','closed_won') GROUP BY {join} ORDER BY revenue DESC"
        ).fetchall()
        out = []
        for r in rows:
            true_cost = self._true_cost_for_segment(join, r["segment"])
            rev = r["revenue"] or 0
            out.append({
                "segment": r["segment"] or "unknown",
                "deals": r["deals"],
                "revenue": round(rev, 2),
                "true_cost": round(true_cost, 2),
                "gross_margin": round((rev - true_cost) / rev, 4) if rev else None,
            })
        return out

    def _true_cost_for_segment(self, join_sql: str, segment_value: str) -> float:
        import json

        rows = self.db.execute(
            f"SELECT p.calculated_result FROM pricing_snapshots p "
            f"JOIN opportunities o ON o.opportunity_id = p.opportunity_id "
            f"JOIN leads l ON l.lead_id = o.lead_id "
            f"WHERE o.stage IN ('won','closed_won') AND {join_sql} = ?",
            (segment_value,),
        ).fetchall()
        total = 0.0
        for r in rows:
            try:
                total += float(json.loads(r["calculated_result"] or "{}").get("true_cost") or 0.0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return total

    def conversion_by(self, column: str) -> list[dict]:
        """Lead → qualified → won conversion per segment."""
        col = column if column in ("market", "source_channel") else "source_channel"
        rows = self.db.execute(
            f"SELECT {col} AS segment, COUNT(*) AS leads, "
            f"SUM(CASE WHEN lead_stage IN ('qualified','hot','won') THEN 1 ELSE 0 END) AS qualified "
            f"FROM leads GROUP BY {col} ORDER BY leads DESC"
        ).fetchall()
        out = []
        for r in rows:
            leads = r["leads"] or 0
            qualified = r["qualified"] or 0
            out.append({
                "segment": r["segment"] or "unknown",
                "leads": leads,
                "qualified": qualified,
                "qualified_rate": round(qualified / leads, 4) if leads else None,
            })
        return out
