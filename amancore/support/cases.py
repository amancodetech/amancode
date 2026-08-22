"""Support Case store — the ONLY gateway to support_cases table.

Support cases are bounded: the agent may create/update them, but refunds,
contract/price/scope changes, and binding commitments are NEVER recorded here —
they require owner approval elsewhere.
"""

from __future__ import annotations

from typing import Any

from ..errors import NotFoundError
from ..ids import new_id, utcnow
from ..storage.db import Database

STATUSES = {"open", "in_progress", "waiting_customer", "waiting_owner", "resolved", "closed", "cancelled"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


class SupportCaseStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        category: str,
        *,
        customer_id: str | None = None,
        lead_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        priority: str = "LOW",
        summary: str = "",
        description: str = "",
        requested_action: str = "",
        owner: str | None = None,
        sla_policy: str | None = None,
    ) -> str:
        priority = priority.upper()
        if priority not in PRIORITIES:
            raise ValueError(f"invalid priority: {priority}")
        case_id = new_id()
        now = utcnow()
        self.db.execute(
            "INSERT INTO support_cases (case_id, customer_id, lead_id, project_id, "
            "conversation_id, category, priority, status, summary, description, "
            "requested_action, owner, escalated, sla_policy, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                case_id, customer_id, lead_id, project_id, conversation_id,
                category, priority, summary or "", description or "",
                requested_action or "", owner, sla_policy, now, now,
            ),
        )
        self.db.commit()
        return case_id

    def get(self, case_id: str) -> dict | None:
        return _row(self.db.execute("SELECT * FROM support_cases WHERE case_id = ?", (case_id,)).fetchone())

    def update(self, case_id: str, **fields: Any) -> None:
        if self.get(case_id) is None:
            raise NotFoundError(f"support case {case_id} not found")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE support_cases SET {', '.join(sets)}, updated_at = ? WHERE case_id = ?",
            (*fields.values(), utcnow(), case_id),
        )
        self.db.commit()

    def list(
        self,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        customer_id: str | None = None,
        lead_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM support_cases WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if priority:
            sql += " AND priority = ?"
            params.append(priority.upper())
        if customer_id:
            sql += " AND customer_id = ?"
            params.append(customer_id)
        if lead_id:
            sql += " AND lead_id = ?"
            params.append(lead_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    # ---- lifecycle ----------------------------------------------------
    def set_status(self, case_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        now = utcnow()
        fields: dict[str, Any] = {"status": status}
        if status == "resolved":
            fields["resolved_at"] = now
        if status in ("open", "in_progress") and self.get(case_id).get("resolved_at"):
            fields["reopened_at"] = now
        self.update(case_id, **fields)

    def set_priority(self, case_id: str, priority: str) -> None:
        priority = priority.upper()
        if priority not in PRIORITIES:
            raise ValueError(f"invalid priority: {priority}")
        self.update(case_id, priority=priority)

    def escalate(self, case_id: str, owner: str | None = None) -> None:
        fields: dict[str, Any] = {"escalated": 1}
        if owner:
            fields["owner"] = owner
        if self.get(case_id)["status"] == "open":
            fields["status"] = "waiting_owner"
        self.update(case_id, **fields)

    def counts(self) -> dict:
        rows = self.db.execute(
            "SELECT status, COUNT(*) AS c FROM support_cases GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}
