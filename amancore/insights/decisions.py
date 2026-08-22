"""Decision Support Service — owner decision workflow.

list/get insights & recommendations · accept/reject/defer · request more data.
Accepting a recommendation NEVER changes the business by itself:
  - approval-required types create an Approval Request (owner must still approve).
  - strategic change (pricing/offer/policy/market/capacity) can additionally
    stage a Business Brain Change PROPOSAL via BrainWriter.propose — the owner
    then completes the existing Brain Writer approval flow. No shortcut.
"""

from __future__ import annotations

from ..errors import NotFoundError, PermissionDenied
from ..ids import new_id, utcnow
from .model import APPROVAL_REQUIRED_TYPES
from .memory import InsightMemory

DECISION_ACTIONS = ("accept", "reject", "defer")


class DecisionSupportService:
    def __init__(self, db, memory=None, approval_service=None, brain_writer=None,
                 audit=None, dispatcher=None):
        self.db = db
        self.memory = memory or InsightMemory(db)
        self.approvals = approval_service
        self.brain_writer = brain_writer
        self.audit = audit
        self.dispatcher = dispatcher

    # ---- read -----------------------------------------------------------
    def list_insights(self, status=None, category=None, limit=100) -> list[dict]:
        return self.memory.list_insights(status=status, category=category, limit=limit)

    def get_insight(self, insight_id: str) -> dict:
        insight = self.memory.get_insight(insight_id)
        if insight is None:
            raise NotFoundError(f"insight {insight_id} not found")
        return insight

    def list_recommendations(self, status=None, limit=100) -> list[dict]:
        return self.memory.list_recommendations(status=status, limit=limit)

    def get_recommendation(self, recommendation_id: str) -> dict:
        rec = self.memory.get_recommendation(recommendation_id)
        if rec is None:
            raise NotFoundError(f"recommendation {recommendation_id} not found")
        return rec

    # ---- decisions ------------------------------------------------------
    def _log_and_audit(self, entity_type: str, entity_id: str, decision: str,
                       decided_by: str, reason: str) -> str:
        decision_id = self.memory.record_decision(
            entity_type, entity_id, decision, decided_by, reason
        )
        if self.audit is not None:
            self.audit.record(
                action="decision.recorded", resource=entity_type,
                actor=decided_by, result=f"{decision} {entity_id}",
            )
        if self.dispatcher is not None:
            from ..services.events import CanonicalEvent

            self.dispatcher.publish(CanonicalEvent(
                event_id=new_id(), event_type="decision.recorded",
                timestamp=utcnow(), source="decision_support",
                actor_type="owner", actor_id=decided_by,
                payload={"entity_type": entity_type, "entity_id": entity_id, "decision": decision},
            ))
        return decision_id

    def accept(self, recommendation_id: str, decided_by: str = "owner", reason: str = "") -> dict:
        rec = self.get_recommendation(recommendation_id)
        if rec["status"] not in ("new", "under_review", "deferred"):
            raise PermissionDenied(f"recommendation already decided: {rec['status']}")
        approval_id = None
        brain_proposal_id = None

        # approval-required types => create an Approval Request (no shortcut)
        if rec["type"] in APPROVAL_REQUIRED_TYPES:
            if self.approvals is None:
                raise PermissionDenied(
                    "recommendation requires owner approval but no approval service is wired"
                )
            approval_id = self.approvals.create_approval_request(
                type_=f"recommendation.{rec['type']}",
                requested_by=f"insights:{rec['recommendation_id']}",
                risk_level="high",
                reason=rec["title"],
                payload={
                    "recommendation_id": recommendation_id,
                    "insight_id": rec["insight_id"],
                    "proposed_action": rec["proposed_action"],
                    "evidence_ids": rec["evidence"],
                },
                policy_reference="recommendation_owner_approval",
            )

        self.memory.update_recommendation(
            recommendation_id, status="accepted", decision="accepted",
            decided_by=decided_by, decided_at=utcnow(), approval_id=approval_id,
        )
        self.memory.update_insight(rec["insight_id"], status="accepted",
                                   recommendation_id=recommendation_id)
        self._log_and_audit("recommendation", recommendation_id, "accepted", decided_by, reason)

        result = {
            "recommendation_id": recommendation_id,
            "decision": "accepted",
            "approval_id": approval_id,
            "note": "accepted — no automatic business change. Approval required for implementation."
                    if approval_id else "accepted — no approval required.",
        }
        if approval_id:
            result["brain_change_proposal"] = self._stage_brain_change(rec, decided_by)
            if result["brain_change_proposal"]:
                result["note"] += (" Brain change PROPOSAL staged (not committed). "
                                   "Owner must complete the Brain Writer approval flow.")
        return result

    def _stage_brain_change(self, rec: dict, decided_by: str) -> dict | None:
        """Stage a PROPOSAL only (never mutate). Strategic types only."""
        if self.brain_writer is None:
            return None
        if rec["type"] not in ("change_pricing", "change_offer", "change_policy", "capacity"):
            return None
        current_version, current_content = self.brain_writer.store.current()
        proposal_content = self._draft_brain_content(current_content, rec)
        if proposal_content is None:
            return None
        try:
            pid = self.brain_writer.propose(
                proposal_content,
                requested_by=f"insights:{rec['recommendation_id']}",
                reason=f"From recommendation {rec['recommendation_id']}: {rec['title']}",
            )
            self.memory.update_recommendation(rec["recommendation_id"], brain_change_proposal_id=pid)
            return {"proposal_id": pid, "status": "pending", "current_version": current_version}
        except Exception as exc:  # noqa: BLE001 — proposal staging must never crash a decision
            from ..log import get_logger

            get_logger("insights.decisions").warning(
                "brain change proposal staging failed: %s", exc
            )
            return None

    def _draft_brain_content(self, current_content: dict, rec: dict) -> dict | None:
        """Deterministic draft with a marker + evidence reference.

        IMPORTANT: this only marks the AREA to review; values are NOT changed.
        The owner must complete the diff/review via the Brain Writer flow.
        """
        import copy

        draft = copy.deepcopy(current_content)
        draft.setdefault("change_proposals", [])
        draft["change_proposals"] = list(current_content.get("change_proposals", [])) + [{
            "proposal_id": f"pending-{rec['recommendation_id'][:8]}",
            "area": rec["type"],
            "evidence_ids": rec.get("evidence", {}).get("evidence_ids", []),
            "status": "pending_owner_review",
            "note": "Review only — values intentionally unchanged.",
        }]
        return draft

    def reject(self, recommendation_id: str, decided_by: str = "owner", reason: str = "") -> dict:
        rec = self.get_recommendation(recommendation_id)
        if rec["status"] not in ("new", "under_review", "deferred"):
            raise PermissionDenied(f"recommendation already decided: {rec['status']}")
        self.memory.update_recommendation(
            recommendation_id, status="rejected", decision="rejected",
            decided_by=decided_by, decided_at=utcnow(),
        )
        self.memory.update_insight(rec["insight_id"], status="rejected")
        self._log_and_audit("recommendation", recommendation_id, "rejected", decided_by, reason)
        return {"recommendation_id": recommendation_id, "decision": "rejected"}

    def defer(self, recommendation_id: str, decided_by: str = "owner", reason: str = "") -> dict:
        rec = self.get_recommendation(recommendation_id)
        if rec["status"] not in ("new", "under_review"):
            raise PermissionDenied(f"recommendation already decided: {rec['status']}")
        self.memory.update_recommendation(
            recommendation_id, status="deferred", decision="deferred",
            decided_by=decided_by, decided_at=utcnow(),
        )
        self.memory.update_insight(rec["insight_id"], status="reviewed")
        self._log_and_audit("recommendation", recommendation_id, "deferred", decided_by, reason)
        return {"recommendation_id": recommendation_id, "decision": "deferred"}

    def request_more_data(self, insight_id: str, decided_by: str = "owner", note: str = "") -> dict:
        insight = self.get_insight(insight_id)
        self.memory.update_insight(insight_id, status="reviewed")
        self._log_and_audit("insight", insight_id, "more_data", decided_by, note)
        return {"insight_id": insight_id, "decision": "more_data_requested"}
