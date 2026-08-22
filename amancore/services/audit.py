"""Audit Service — append-only, immutable audit trail."""

from __future__ import annotations

from typing import Any

from ..errors import AuditError
from ..ids import new_id, utcnow
from ..storage.db import Database


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        action: str,
        resource: str,
        actor: str | None = None,
        agent: str | None = None,
        old_value: str | None = None,
        new_value: str | None = None,
        reason: str | None = None,
        approval_id: str | None = None,
        correlation_id: str | None = None,
        result: str | None = None,
    ) -> str:
        audit_id = new_id()
        self.db.execute(
            "INSERT INTO audit_events "
            "(audit_id, timestamp, actor, agent, action, resource, old_value, new_value, "
            " reason, approval_id, correlation_id, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                utcnow(),
                actor,
                agent,
                action,
                resource,
                old_value,
                new_value,
                reason,
                approval_id,
                correlation_id,
                result,
            ),
        )
        self.db.commit()
        return audit_id

    def query(
        self,
        action: str | None = None,
        correlation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM audit_events WHERE 1=1"
        params: list[Any] = []
        if action:
            sql += " AND action = ?"
            params.append(action)
        if correlation_id:
            sql += " AND correlation_id = ?"
            params.append(correlation_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
