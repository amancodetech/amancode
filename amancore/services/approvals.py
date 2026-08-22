"""Approval Service — auditable human-approval workflow."""

from __future__ import annotations

from typing import Any

from ..errors import ApprovalError, NotFoundError
from ..ids import new_id, utcnow
from ..storage.db import Database

STATUSES = {"pending", "approved", "rejected", "edited", "expired", "cancelled"}


class ApprovalService:
    def __init__(self, db: Database, audit=None):
        self.db = db
        self.audit = audit

    def create_approval_request(
        self,
        type_: str,
        requested_by: str,
        risk_level: str,
        reason: str,
        payload: dict | None = None,
        policy_reference: str | None = None,
    ) -> str:
        approval_id = new_id()
        import json

        self.db.execute(
            "INSERT INTO approvals "
            "(approval_id, type, requested_by, requested_at, risk_level, reason, payload, "
            " policy_reference, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                approval_id,
                type_,
                requested_by,
                utcnow(),
                risk_level,
                reason,
                json.dumps(payload or {}, ensure_ascii=False),
                policy_reference,
            ),
        )
        self.db.commit()
        self._audit("approval.requested", approval_id, requested_by, "pending")
        return approval_id

    def get(self, approval_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return dict(row) if row else None

    def _require_pending(self, approval_id: str) -> dict:
        row = self.get(approval_id)
        if row is None:
            raise NotFoundError(f"approval {approval_id} not found")
        if row["status"] != "pending":
            raise ApprovalError(f"approval {approval_id} is not pending")
        return row

    def approve(self, approval_id: str, approved_by: str, decision: str = "approved") -> None:
        self._require_pending(approval_id)
        self._decide(approval_id, approved_by, "approved", decision)

    def reject(self, approval_id: str, approved_by: str, reason: str) -> None:
        self._require_pending(approval_id)
        self._decide(approval_id, approved_by, "rejected", reason)

    def edit(self, approval_id: str, approved_by: str, decision: str) -> None:
        self._require_pending(approval_id)
        self._decide(approval_id, approved_by, "edited", decision)

    def expire(self, approval_id: str) -> None:
        self._require_pending(approval_id)
        self.db.execute(
            "UPDATE approvals SET status = 'expired', decided_at = ? WHERE approval_id = ?",
            (utcnow(), approval_id),
        )
        self.db.commit()

    def cancel(self, approval_id: str, by: str) -> None:
        self._require_pending(approval_id)
        self.db.execute(
            "UPDATE approvals SET status = 'cancelled', approved_by = ?, decided_at = ? "
            "WHERE approval_id = ?",
            (by, utcnow(), approval_id),
        )
        self.db.commit()

    def _decide(self, approval_id: str, approved_by: str, status: str, decision: str) -> None:
        self.db.execute(
            "UPDATE approvals SET status = ?, approved_by = ?, decision = ?, decided_at = ? "
            "WHERE approval_id = ?",
            (status, approved_by, decision, utcnow(), approval_id),
        )
        self.db.commit()
        self._audit(f"approval.{status}", approval_id, approved_by, decision)

    def _audit(self, action: str, approval_id: str, actor: str, decision: str) -> None:
        if self.audit is not None:
            self.audit.record(
                action=action,
                resource="approvals",
                actor=actor,
                approval_id=approval_id,
                result=decision,
            )
