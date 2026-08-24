"""AlertService — deterministic alert policies (configs/alerts.yaml).

Checks are read-only. Triggered alerts are returned; owner alerts are emitted
for severity high/critical when an owner_alert sink is provided.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..ids import utcnow
from ..storage.db import Database


def _ago(days: float = 0, hours: float = 0) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    ).isoformat()


class AlertService:
    def __init__(self, db: Database, config: dict | None = None, owner_alert=None):
        self.db = db
        self.config = (config or {}).get("alerts", {})
        self.owner_alert = owner_alert

    def check_all(self) -> list[dict]:
        alerts: list[dict] = []
        alerts += self._system_checks()
        alerts += self._sales_checks()
        alerts += self._pricing_checks()
        alerts += self._support_checks()
        alerts += self._ai_checks()
        return alerts

    def _add(self, alerts: list[dict], name: str, severity: str, detail: str, policy: dict) -> None:
        alerts.append({"alert": name, "severity": severity, "detail": detail, "policy": policy.get("name")})
        if severity in ("high", "critical") and self.owner_alert is not None:
            self.owner_alert(severity, f"[ALERT] {name}: {detail}", None, event_type="threshold", resource=str(name))

    def _policy(self, group: str, key: str) -> dict:
        return self.config.get(group, {}).get(key, {})

    # ---- System --------------------------------------------------------
    def _system_checks(self) -> list[dict]:
        out: list[dict] = []

        p = self._policy("system", "repeated_errors")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type LIKE '%failed%' AND timestamp >= ?",
                (_ago(hours=24),),
            ).fetchone()["c"]
            if n >= p.get("threshold", 5):
                self._add(out, "repeated_errors", p.get("severity", "high"), f"{n} failure events in 24h", p)

        p = self._policy("system", "api_failures")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM usage_records WHERE status = 'error' AND created_at >= ?",
                (_ago(hours=1),),
            ).fetchone()["c"]
            if n >= p.get("threshold", 3):
                self._add(out, "api_failures", p.get("severity", "high"), f"{n} provider errors in 1h", p)

        p = self._policy("system", "dead_letter_growth")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM message_outbox WHERE status = 'dead'"
            ).fetchone()["c"]
            if n >= p.get("threshold", 3):
                self._add(out, "dead_letter_growth", p.get("severity", "high"), f"{n} dead-letter messages", p)
        return out

    # ---- Sales ---------------------------------------------------------
    def _sales_checks(self) -> list[dict]:
        out: list[dict] = []

        p = self._policy("sales", "hot_lead_waiting")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE lead_stage = 'hot' "
                "AND (next_followup_at IS NULL OR next_followup_at < ?)",
                (_ago(hours=24),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "hot_lead_waiting", p.get("severity", "high"), f"{n} hot lead(s) waiting", p)

        p = self._policy("sales", "high_value_opportunity_pending")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM opportunities "
                "WHERE estimated_value >= ? AND stage NOT IN ('won','lost','closed_won','closed_lost')",
                (p.get("threshold_value", 1000),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "high_value_opportunity_pending", p.get("severity", "medium"), f"{n} high-value open", p)

        p = self._policy("sales", "proposal_pending")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM proposals WHERE status = 'approved' AND updated_at < ?",
                (_ago(days=p.get("threshold_days", 3)),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "proposal_pending", p.get("severity", "medium"), f"{n} approved proposal(s) pending", p)
        return out

    # ---- Pricing -------------------------------------------------------
    def _pricing_checks(self) -> list[dict]:
        out: list[dict] = []

        p = self._policy("pricing", "approval_pending")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM approvals WHERE status = 'pending' "
                "AND (type LIKE '%pricing%' OR reason LIKE '%price%') AND requested_at < ?",
                (_ago(days=p.get("threshold_days", 2)),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "approval_pending", p.get("severity", "medium"), f"{n} pricing approval(s) pending", p)

        p = self._policy("pricing", "pricing_warning")
        if p:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type = 'pricing.warning' AND timestamp >= ?",
                (_ago(hours=24),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "pricing_warning", p.get("severity", "medium"), f"{n} pricing warnings in 24h", p)
        return out

    # ---- Support -------------------------------------------------------
    def _support_checks(self) -> list[dict]:
        out: list[dict] = []
        active = "('open','in_progress','waiting_customer','waiting_owner')"

        p = self._policy("support", "critical_support")
        if p:
            n = self.db.execute(
                f"SELECT COUNT(*) AS c FROM support_cases WHERE priority = 'CRITICAL' AND status IN {active}"
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "critical_support", p.get("severity", "critical"), f"{n} open CRITICAL case(s)", p)

        p = self._policy("support", "stale_case")
        if p:
            n = self.db.execute(
                f"SELECT COUNT(*) AS c FROM support_cases WHERE status IN {active} AND updated_at < ?",
                (_ago(days=p.get("threshold_days", 2)),),
            ).fetchone()["c"]
            if n >= 1:
                self._add(out, "stale_case", p.get("severity", "medium"), f"{n} stale case(s)", p)
        return out

    # ---- AI ------------------------------------------------------------
    def _ai_checks(self) -> list[dict]:
        out: list[dict] = []

        p = self._policy("ai", "token_budget_exceeded")
        if p:
            n = self.db.execute(
                "SELECT COALESCE(SUM(input_tokens + output_tokens),0) AS c FROM usage_records WHERE created_at >= ?",
                (_ago(hours=24),),
            ).fetchone()["c"]
            if n >= p.get("threshold_tokens", 1_000_000):
                self._add(out, "token_budget_exceeded", p.get("severity", "high"), f"{n} tokens in 24h", p)

        p = self._policy("ai", "cost_spike")
        if p:
            today = self.db.execute(
                "SELECT COALESCE(SUM(estimated_cost),0) AS c FROM usage_records WHERE created_at >= ?",
                (_ago(hours=24),),
            ).fetchone()["c"]
            yesterday = self.db.execute(
                "SELECT COALESCE(SUM(estimated_cost),0) AS c FROM usage_records "
                "WHERE created_at >= ? AND created_at < ?",
                (_ago(days=2), _ago(days=1)),
            ).fetchone()["c"]
            if today and yesterday and today > yesterday * p.get("multiplier", 2):
                self._add(out, "cost_spike", p.get("severity", "high"),
                          f"today {today:.2f} vs yesterday {yesterday:.2f}", p)
        return out
