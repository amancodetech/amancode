"""Risk Engine — deterministic, no LLM."""

from __future__ import annotations

from ..errors import RiskError

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

# event_type -> default risk level
_EVENT_RISK = {
    # critical actions (override by action, not event)
    "price.calculated": HIGH,
    "offer.generated": HIGH,
    "negotiation.started": HIGH,
    "proposal.created": HIGH,
    "proposal.sent": HIGH,
    "message.sent": MEDIUM,
    "message.failed": MEDIUM,
    "lead.scored": MEDIUM,
    "conversation.received": MEDIUM,
    "conversation.updated": MEDIUM,
    "followup.due": MEDIUM,
    "followup.sent": MEDIUM,
    "deal.won": MEDIUM,
    "deal.lost": MEDIUM,
    "project.created": MEDIUM,
    "project.updated": MEDIUM,
    "care_plan.created": MEDIUM,
    "content.approved": MEDIUM,
    "content.published": MEDIUM,
    # internal bookkeeping
    "lead.created": LOW,
    "lead.updated": LOW,
    "content.drafted": LOW,
    "job.created": LOW,
    "job.completed": LOW,
    "job.failed": LOW,
    "approval.requested": LOW,
    "approval.approved": LOW,
    "approval.rejected": LOW,
}

_CRITICAL_ACTIONS = {
    "contract", "refund", "legal", "security_incident",
    "data_breach", "sensitive_complaint", "unknown_policy",
}
_HIGH_ACTIONS = {"price_approval", "negotiation", "proposal", "discount"}


class RiskEngine:
    def classify(self, event_type: str, action: str | None = None) -> str:
        if action in _CRITICAL_ACTIONS:
            return CRITICAL
        if action in _HIGH_ACTIONS:
            return HIGH
        if event_type not in _EVENT_RISK:
            raise RiskError(f"unknown event_type for risk classification: {event_type}")
        return _EVENT_RISK[event_type]
