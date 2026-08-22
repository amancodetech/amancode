"""Job registry — maps job types to deterministic handlers.

Handlers read-only where possible; no automatic business changes.
Jobs with insufficient data are safe no-ops (research.daily stays off).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..log import get_logger

log = get_logger("ops.registry")

# job type -> schedule key in configs/scheduler.yaml
JOB_TYPES = (
    "research.daily", "followups.check",
    "analytics.daily", "analytics.weekly", "analytics.monthly",
    "insights.daily", "insights.weekly", "insights.monthly",
    "retention.cleanup", "database.backup", "backup.verify",
    "health.check", "production.check",
)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class JobRegistry:
    """Builds handlers bound to the live services. Deterministic."""

    def __init__(self, db, config, root):
        self.db = db
        self.config = config
        self.root = root

    def handlers(self) -> dict:
        cfg = self.config

        def _analytics(period: str):
            from ..analytics.service import AnalyticsService
            from ..insights.reports import InsightReports
            from ..insights.memory import InsightMemory

            analytics = AnalyticsService(self.db, config=cfg.analytics)
            reports = InsightReports(self.db, analytics, InsightMemory(self.db))
            if period == "daily":
                return reports.daily_brief(_today())
            if period == "weekly":
                return reports.weekly_review()
            return reports.monthly_review()

        def _insights(days: int):
            from ..analytics.service import AnalyticsService
            from ..insights.engine import InsightsEngine

            engine = InsightsEngine(self.db, analytics=AnalyticsService(self.db, config=cfg.analytics),
                                    config=cfg.insights)
            return engine.run(period_days=days)

        def _followups():
            from ..ids import utcnow

            due = self.db.execute(
                "SELECT lead_id, name, company, next_followup_at FROM leads "
                "WHERE next_followup_at IS NOT NULL AND next_followup_at <= ? AND opt_out = 0",
                (utcnow(),),
            ).fetchall()
            for r in due:
                from ..ids import new_id

                from ..services.events import CanonicalEvent
                from ..services.events import EventDispatcher

                dispatcher = EventDispatcher()
                dispatcher.publish(CanonicalEvent(
                    event_id=new_id(), event_type="followup.due",
                    timestamp=utcnow(), source="scheduler", actor_type="system",
                    payload={"lead_id": r["lead_id"]},
                ))
            return {"due_followups": len(due), "leads": [r["lead_id"] for r in due]}

        def _retention():
            from ..ops.retention import RetentionService

            return RetentionService(self.db, config=cfg.retention).run()

        def _backup():
            from ..ops.backup import BackupService

            return BackupService(self.db, self.root).create_backup(kind="all")

        def _backup_verify():
            from ..ops.backup import BackupService

            return BackupService(self.db, self.root).verify_latest()

        def _health():
            from ..health import run_health_checks

            results = run_health_checks(self.root)
            return {"result": "PASS" if all(s == "PASS" for s, _ in results.values()) else "FAIL",
                    "checks": len(results)}

        def _production_check():
            from ..production.gate import ProductionGateService

            production = dict(cfg.production)
            production["_root"] = self.root
            report = ProductionGateService(production).check()
            return {"verdict": report["verdict"], "production_enabled": report["production_enabled"]}

        return {
            "research.daily": lambda payload: {"note": "disabled (no live research router in mock mode)"},
            "followups.check": lambda p: _followups(),
            "analytics.daily": lambda p: _analytics("daily"),
            "analytics.weekly": lambda p: _analytics("weekly"),
            "analytics.monthly": lambda p: _analytics("monthly"),
            "insights.daily": lambda p: _insights(1),
            "insights.weekly": lambda p: _insights(7),
            "insights.monthly": lambda p: _insights(30),
            "retention.cleanup": lambda p: _retention(),
            "database.backup": lambda p: _backup(),
            "backup.verify": lambda p: _backup_verify(),
            "health.check": lambda p: _health(),
            "production.check": lambda p: _production_check(),
        }
