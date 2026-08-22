"""Opportunity Detection — hot leads, high-value pending, market score,
SaaS/product candidates. Deterministic; detection only, never a decision.

Market Opportunity Score is evidence-based and never changes the primary/
secondary market by itself.
"""

from __future__ import annotations

from ..ids import utcnow


class OpportunityDetector:
    def __init__(self, db, analytics, config=None):
        self.db = db
        self.analytics = analytics
        self.config = config or {}

    def hot_leads_waiting(self, hours: int = 24) -> list[dict]:
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self.db.execute(
            "SELECT lead_id, name, company, lead_score, next_followup_at, last_contact_at "
            "FROM leads WHERE lead_stage = 'hot' "
            "AND (next_followup_at IS NULL OR next_followup_at < ?) ORDER BY lead_score DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def high_value_opportunities(self, threshold: float = 1000) -> list[dict]:
        rows = self.db.execute(
            "SELECT o.opportunity_id, o.service, o.estimated_value, o.stage, "
            "l.name, l.company, o.created_at "
            "FROM opportunities o JOIN leads l ON l.lead_id = o.lead_id "
            "WHERE COALESCE(o.estimated_value,0) >= ? "
            "AND o.stage NOT IN ('won','lost','closed_won','closed_lost') "
            "ORDER BY o.estimated_value DESC LIMIT 20",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]

    def pending_proposals(self, days: int = 3) -> list[dict]:
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.db.execute(
            "SELECT p.proposal_id, p.opportunity_id, p.status, p.updated_at "
            "FROM proposals p WHERE p.status = 'approved' AND p.updated_at < ?",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def saas_candidates(self) -> list[dict]:
        """Same problem repeated across N+ customers -> product opportunity (owner decides)."""
        from ..insights.optimizers import OptimizationAnalyzer

        recurring = OptimizationAnalyzer(self.db, self.analytics).recurring_issues(
            threshold=int(self.config.get("saas_candidate_min_customers", 2))
        )
        candidates = []
        for issue in recurring:
            candidates.append({
                "problem": issue["category"],
                "frequency": issue["count"],
                "customers_affected": issue["count"],
                "consistency": "repeated",
                "willingness_signal": None,  # no payment intent data yet
                "evidence": issue["examples"],
                "confidence": "HIGH" if issue["count"] >= 5 else "MEDIUM",
            })
        return candidates

    def market_opportunity_score(self) -> list[dict]:
        """Score each market from ACTUAL data. Never changes market selection."""
        rows = self.db.execute(
            "SELECT l.market, COUNT(*) AS leads, "
            "SUM(CASE WHEN l.lead_stage IN ('qualified','hot') THEN 1 ELSE 0 END) AS qualified, "
            "COUNT(DISTINCT CASE WHEN o.stage IN ('won','closed_won') THEN o.opportunity_id END) AS won "
            "FROM leads l LEFT JOIN opportunities o ON o.lead_id = l.lead_id "
            "GROUP BY l.market"
        ).fetchall()
        out = []
        for r in rows:
            market = r["market"]
            if not market:
                continue
            leads = r["leads"] or 0
            qualified = r["qualified"] or 0
            won = r["won"] or 0
            score = round(
                (0.3 * (qualified / max(leads, 1))) +
                (0.5 * (won / max(leads, 1))) +
                (0.2 * min(leads / 10, 1)),
                4,
            )
            out.append({
                "market": market,
                "leads": leads,
                "qualified": qualified,
                "won": won,
                "score": score,
                "sample_size": leads,
            })
        return sorted(out, key=lambda x: -x["score"])
