"""Data Quality checks — issues become Data Quality Insights, never fixes.

Checks: missing source · missing customer · inconsistent revenue · negative
cost · opportunity without lead · proposal without snapshot · won without
revenue · support case without customer · impossible dates.
"""

from __future__ import annotations

import json


class DataQualityService:
    def __init__(self, db):
        self.db = db

    def run_checks(self) -> list[dict]:
        issues: list[dict] = []
        issues += self._missing_source()
        issues += self._negative_cost()
        issues += self._opportunity_without_lead()
        issues += self._proposal_without_snapshot()
        issues += self._won_without_revenue()
        issues += self._support_without_customer()
        issues += self._impossible_dates()
        return issues

    def _issue(self, entity: str, field: str, problem: str, affected: int,
               severity: str = "LOW", recommendation: str = "") -> dict:
        return {
            "entity": entity, "field": field, "problem": problem,
            "affected_records": affected, "severity": severity,
            "recommendation": recommendation,
        }

    def _missing_source(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE source_channel IS NULL OR source_channel = ''"
        ).fetchone()["c"]
        return [self._issue("leads", "source_channel", "lead without acquisition source", n or 0,
                            "LOW", "fill source at intake")] if n else []

    def _negative_cost(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM pricing_snapshots WHERE approved_price < 0"
        ).fetchone()["c"]
        return [self._issue("pricing_snapshots", "approved_price", "negative approved price", n or 0,
                            "HIGH", "review pricing")] if n else []

    def _opportunity_without_lead(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM opportunities WHERE lead_id IS NULL OR lead_id = ''"
        ).fetchone()["c"]
        return [self._issue("opportunities", "lead_id", "opportunity without lead", n or 0,
                            "MEDIUM", "link lead")] if n else []

    def _proposal_without_snapshot(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM proposals WHERE pricing_snapshot_id IS NULL"
        ).fetchone()["c"]
        return [self._issue("proposals", "pricing_snapshot_id", "proposal without pricing snapshot", n or 0,
                            "MEDIUM", "attach approved snapshot")] if n else []

    def _won_without_revenue(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM opportunities o WHERE o.stage IN ('won','closed_won') "
            "AND NOT EXISTS (SELECT 1 FROM pricing_snapshots p "
            "WHERE p.opportunity_id = o.opportunity_id AND p.approved_price IS NOT NULL)"
        ).fetchone()["c"]
        return [self._issue("opportunities", "approved_price", "won deal without revenue", n or 0,
                            "HIGH", "attach approved snapshot")] if n else []

    def _support_without_customer(self) -> list[dict]:
        n = self.db.execute(
            "SELECT COUNT(*) AS c FROM support_cases WHERE customer_id IS NULL AND lead_id IS NULL"
        ).fetchone()["c"]
        return [self._issue("support_cases", "customer_id", "support case without customer/lead", n or 0,
                            "LOW", "attach customer")] if n else []

    def _impossible_dates(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT lead_id FROM leads WHERE created_at > datetime('now')"
        ).fetchall()
        return [self._issue("leads", "created_at", "impossible future date", len(rows),
                            "MEDIUM", "fix timestamp")] if rows else []
