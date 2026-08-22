"""Local monitoring — structured status via SQLite + system + CLI.

No Grafana/Prometheus: enough for a local-first system. Covers system, jobs,
channels, AI, business. Read-only.
"""

from __future__ import annotations

import os
import shutil

from ..ids import utcnow
from ..storage.db import Database


class MonitoringService:
    def __init__(self, db: Database, root):
        self.db = db
        self.root = root

    def status(self) -> dict:
        return {
            "checked_at": utcnow(),
            "system": self.system(),
            "jobs": self.jobs(),
            "channels": self.channels(),
            "ai": self.ai(),
            "business": self.business(),
        }

    # ---- system ---------------------------------------------------------
    def system(self) -> dict:
        loadavg = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
        try:
            disk = shutil.disk_usage(str(self.root))
            disk_usage = {"total_gb": round(disk.total / 1e9, 1),
                          "used_gb": round(disk.used / 1e9, 1),
                          "free_gb": round(disk.free / 1e9, 1)}
        except Exception:  # noqa: BLE001
            disk_usage = {"error": "unavailable"}
        return {"loadavg": list(loadavg) if any(loadavg) else None, "disk": disk_usage,
                "cwd": str(self.root)}

    # ---- jobs -----------------------------------------------------------
    def jobs(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()
        counts = {r["status"]: r["c"] for r in rows}
        return {
            "counts": counts,
            "dead": counts.get("dead", 0),
            "running": counts.get("running", 0),
            "recent_failures": self.db.execute(
                "SELECT job_id, type, error, created_at FROM jobs "
                "WHERE status IN ('failed','dead') ORDER BY created_at DESC LIMIT 5"
            ).fetchall() and [
                {"job_id": r["job_id"], "type": r["type"], "error": r["error"]}
                for r in self.db.execute(
                    "SELECT job_id, type, error, created_at FROM jobs "
                    "WHERE status IN ('failed','dead') ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
            ],
        }

    # ---- channels -------------------------------------------------------
    def channels(self) -> dict:
        outbox = self.db.execute(
            "SELECT status, COUNT(*) AS c FROM message_outbox GROUP BY status"
        ).fetchall()
        today = utcnow()[:10]
        return {
            "outbox": {r["status"]: r["c"] for r in outbox},
            "inbound_today": self.db.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type = 'whatsapp.message.received' "
                "AND timestamp >= ?", (today,),
            ).fetchone()["c"],
            "outbound_today": self.db.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type IN "
                "('whatsapp.message.sent','message.sent') AND timestamp >= ?", (today,),
            ).fetchone()["c"],
            "webhook_failures_today": self.db.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type = 'whatsapp.webhook.failed' "
                "AND timestamp >= ?", (today,),
            ).fetchone()["c"],
        }

    # ---- AI -------------------------------------------------------------
    def ai(self) -> dict:
        return {
            "cost_total": self.db.execute(
                "SELECT COALESCE(SUM(estimated_cost),0) AS c FROM usage_records"
            ).fetchone()["c"],
            "tokens_total": self.db.execute(
                "SELECT COALESCE(SUM(input_tokens + output_tokens),0) AS c FROM usage_records"
            ).fetchone()["c"],
            "failures_total": self.db.execute(
                "SELECT COUNT(*) AS c FROM usage_records WHERE status = 'error'"
            ).fetchone()["c"],
            "avg_latency_ms": self.db.execute(
                "SELECT COALESCE(AVG(latency_ms),0) AS c FROM usage_records"
            ).fetchone()["c"],
        }

    # ---- business -------------------------------------------------------
    def business(self) -> dict:
        return {
            "leads": self.db.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"],
            "hot_leads": self.db.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE lead_stage = 'hot'"
            ).fetchone()["c"],
            "opportunities_open": self.db.execute(
                "SELECT COUNT(*) AS c FROM opportunities WHERE stage NOT IN "
                "('won','lost','closed_won','closed_lost')"
            ).fetchone()["c"],
            "proposals_approved": self.db.execute(
                "SELECT COUNT(*) AS c FROM proposals WHERE status = 'approved'"
            ).fetchone()["c"],
            "won": self.db.execute(
                "SELECT COUNT(*) AS c FROM opportunities WHERE stage IN ('won','closed_won')"
            ).fetchone()["c"],
            "support_open": self.db.execute(
                "SELECT COUNT(*) AS c FROM support_cases WHERE status IN "
                "('open','in_progress','waiting_customer','waiting_owner')"
            ).fetchone()["c"],
            "alerts_open": self.db.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE status = 'open'"
            ).fetchone()["c"],
            "incidents_open": self.db.execute(
                "SELECT COUNT(*) AS c FROM incidents WHERE status NOT IN ('resolved','closed')"
            ).fetchone()["c"],
        }
