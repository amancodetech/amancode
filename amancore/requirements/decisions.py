"""Decision Tracker — maintains the immutable log of agreed choices and prevents redundant questions."""

from __future__ import annotations

import logging
from typing import Any

from ..ids import new_id, utcnow
from .models import ProjectDecision

log = logging.getLogger("amancore.requirements.decisions")


class DecisionTracker:
    """Manages agreed project decisions (currency, language, tech stack, phases)."""

    def __init__(self, crm):
        self.crm = crm

    def is_decided(self, lead_id: str, topic: str) -> bool:
        """Return True if a topic has an active decision recorded."""
        if not lead_id or not topic:
            return False
        row = self.crm.db.execute(
            "SELECT decision_id FROM project_decisions WHERE lead_id = ? AND topic = ? AND status = 'active' LIMIT 1",
            (lead_id, topic),
        ).fetchone()
        return row is not None

    def get_decision(self, lead_id: str, topic: str) -> str | None:
        """Get the active decision value for a topic."""
        if not lead_id or not topic:
            return None
        row = self.crm.db.execute(
            "SELECT decision FROM project_decisions WHERE lead_id = ? AND topic = ? AND status = 'active' ORDER BY created_at DESC, decision_id DESC LIMIT 1",
            (lead_id, topic),
        ).fetchone()
        return row["decision"] if row else None

    def get_decision_history(self, lead_id: str, topic: str | None = None) -> list[dict]:
        """Fetch all decisions (active and superseded) for auditability."""
        sql = "SELECT * FROM project_decisions WHERE lead_id = ?"
        params: list[Any] = [lead_id]
        if topic:
            sql += " AND topic = ?"
            params.append(topic)
        sql += " ORDER BY created_at ASC"
        return [dict(r) for r in self.crm.db.execute(sql, tuple(params)).fetchall()]

    def record_decision(
        self,
        lead_id: str,
        topic: str,
        decision_value: str,
        rationale: str | None = None,
        source_message_id: str | None = None,
        project_id: str | None = None,
        decided_by: str = "customer",
    ) -> str:
        """Atomically record or update a decision under write transaction lock."""
        if not lead_id or not topic or not decision_value:
            return ""

        with self.crm.db.transaction():
            # Check if an active decision with the exact same value already exists (atomic deduplication)
            row = self.crm.db.execute(
                "SELECT decision_id FROM project_decisions WHERE lead_id = ? AND topic = ? AND status = 'active' AND decision = ? LIMIT 1",
                (lead_id, topic, decision_value),
            ).fetchone()
            if row:
                log.debug("decision.deduplicated lead=%s topic=%s val=%s", lead_id, topic, decision_value)
                return row["decision_id"]

            # Supersede previous active decisions
            self.crm.db.execute(
                "UPDATE project_decisions SET status = 'superseded', updated_at = datetime('now') WHERE lead_id = ? AND topic = ? AND status = 'active'",
                (lead_id, topic),
            )

            # Insert new active decision atomically under the active transaction lock
            dec_id = new_id()
            now = utcnow()
            self.crm.db.execute(
                """
                INSERT INTO project_decisions (
                    decision_id, lead_id, project_id, topic, decision, rationale,
                    source_message_id, decided_by, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    dec_id,
                    lead_id,
                    project_id,
                    topic,
                    decision_value,
                    rationale,
                    source_message_id,
                    decided_by,
                    now,
                    now,
                ),
            )

        log.info("decision.created lead=%s topic=%s val=%s id=%s", lead_id, topic, decision_value, dec_id)
        return dec_id
