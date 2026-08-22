"""Business Brain Writer — deterministic write path.

Flow (Phase 1.1):
    Proposed Change -> Validation -> Policy Check -> Owner Approval
    -> Writer -> New Version -> Diff -> Audit

Agents never write here directly. Only the owner (or, later, the
Orchestrator acting on the owner's behalf) may approve changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..errors import BusinessBrainError, PermissionDenied, ValidationError
from ..ids import new_id, utcnow
from .store import BrainStore
from .validator import validate_brain

_APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired", "cancelled"}


class BrainWriter:
    def __init__(self, store: BrainStore, audit=None, proposals_dir: Path | None = None):
        self.store = store
        self.audit = audit
        self.proposals_dir = proposals_dir or (store.brain_dir / "proposals")

    def _write_proposal(self, proposal: dict) -> str:
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        pid = proposal.get("proposal_id") or new_id()
        proposal["proposal_id"] = pid
        (self.proposals_dir / f"{pid}.json").write_text(
            json.dumps(proposal, indent=2), encoding="utf-8"
        )
        return pid

    def _read_proposal(self, proposal_id: str) -> dict:
        f = self.proposals_dir / f"{proposal_id}.json"
        if not f.exists():
            raise BusinessBrainError(f"proposal not found: {proposal_id}")
        return json.loads(f.read_text(encoding="utf-8"))

    def _audit(self, action: str, resource: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.record(action=action, resource=resource, **fields)

    def propose(self, content: dict, requested_by: str, reason: str) -> str:
        """Validate a proposed change and stage it (status=pending)."""
        errors = validate_brain(content)
        if errors:
            raise ValidationError("; ".join(errors))
        proposal = {
            "requested_by": requested_by,
            "reason": reason,
            "created_at": utcnow(),
            "status": "pending",
            "content": content,
        }
        pid = self._write_proposal(proposal)
        self._audit("business_brain.proposed", "business_brain", proposal_id=pid, reason=reason)
        return pid

    def approve(self, proposal_id: str, approved_by: str) -> int:
        """Validate + persist a new immutable version. Returns new version number."""
        proposal = self._read_proposal(proposal_id)
        if proposal["status"] != "pending":
            raise PermissionDenied(f"proposal {proposal_id} is not pending")
        content = proposal["content"]
        errors = validate_brain(content)
        if errors:
            raise ValidationError("; ".join(errors))

        number = self.store.next_version_number()
        current_number, current_content = self.store.current()
        self.store._append_version(
            number,
            content,
            {
                "created_by": approved_by,
                "reason": proposal["reason"],
                "previous_version": current_number,
                "approval_status": "approved",
                "proposal_id": proposal_id,
            },
        )
        proposal["status"] = "approved"
        proposal["approved_by"] = approved_by
        proposal["approved_at"] = utcnow()
        self._write_proposal(proposal)

        diff = self.store.diff(current_number, number)
        self._audit(
            "business_brain.version_created",
            "business_brain",
            old_value=str(current_number),
            new_value=str(number),
            reason=proposal["reason"],
            approval_id=proposal_id,
        )
        return number

    def reject(self, proposal_id: str, approved_by: str, reason: str) -> None:
        proposal = self._read_proposal(proposal_id)
        proposal["status"] = "rejected"
        proposal["approved_by"] = approved_by
        proposal["rejected_at"] = utcnow()
        proposal["rejection_reason"] = reason
        self._write_proposal(proposal)
        self._audit(
            "business_brain.rejected",
            "business_brain",
            approval_id=proposal_id,
            reason=reason,
        )

    def rollback(self, target_version: int, requested_by: str, approved_by: str, reason: str) -> int:
        """Create a new version whose content equals `target_version`."""
        target_content = self.store.get(target_version)
        pid = self.propose(target_content, requested_by, reason=f"rollback to v{target_version}: {reason}")
        return self.approve(pid, approved_by)
