"""Retention cleanup — policy-driven (configs/retention.yaml).

NEVER deletes protected records: approved pricing snapshots, approved
proposals, customer project history, required audit records, active support
cases, business brain versions. Audit + brain are permanent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.retention")


class RetentionService:
    def __init__(self, db: Database, config: dict | None = None):
        self.db = db
        self.config = config or {}

    def _cutoff(self, key: str, default_days: int) -> str:
        days = int(self.config.get(key, default_days))
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def run(self) -> dict:
        results = {
            "leads_removed": self._clean_leads(),
            "conversations_removed": self._clean_conversations(),
            "content_removed": self._clean_content(),
        }
        # audit + business_brain versions are PERMANENT by policy — never cleaned
        results["audit"] = "permanent (never deleted)"
        results["business_brain_versions"] = "permanent (never deleted)"
        return results

    def _clean_leads(self) -> int:
        cutoff = self._cutoff("lead_inactive_days", 365)
        cur = self.db.execute(
            "DELETE FROM leads WHERE lead_stage = 'nurture' AND created_at < ? "
            "AND NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.lead_id = leads.lead_id) "
            "AND NOT EXISTS (SELECT 1 FROM support_cases sc WHERE sc.lead_id = leads.lead_id) "
            "AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.lead_id = leads.lead_id "
            "  AND COALESCE(c.last_message_at, c.created_at) >= ?)",
            (cutoff, cutoff),
        )
        self.db.commit()
        return cur.rowcount

    def _clean_conversations(self) -> int:
        cutoff = self._cutoff("conversation_active_days", 90)
        cur = self.db.execute(
            "DELETE FROM conversations WHERE COALESCE(last_message_at, created_at) < ? AND lead_id NOT IN ("
            "  SELECT lead_id FROM opportunities WHERE stage NOT IN ('won','lost','closed_won','closed_lost')"
            ") AND lead_id NOT IN ("
            "  SELECT lead_id FROM support_cases WHERE status IN "
            "('open','in_progress','waiting_customer','waiting_owner')"
            ")",
            (cutoff,),
        )
        self.db.commit()
        return cur.rowcount

    def _clean_content(self) -> int:
        cutoff = self._cutoff("content_days", 180)
        cur = self.db.execute(
            "DELETE FROM content_items WHERE status = 'draft' AND created_at < ?",
            (cutoff,),
        )
        self.db.commit()
        return cur.rowcount
