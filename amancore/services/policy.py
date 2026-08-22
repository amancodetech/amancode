"""Policy Engine — deterministic decision from Business Brain + risk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ALLOW = "allow"
APPROVAL_REQUIRED = "approval_required"
ESCALATE = "escalate"
DENY = "deny"


@dataclass
class PolicyDecision:
    action: str
    policy_reference: str
    reason: str


class PolicyEngine:
    def evaluate(
        self,
        brain: dict[str, Any],
        event_type: str,
        risk_level: str,
        action: str | None = None,
    ) -> PolicyDecision:
        """Return allow / approval_required / escalate / deny."""
        decision_policies = brain.get("decision_policies", {})

        if action == "legal" or decision_policies.get("legal") == "escalate_to_owner":
            if action == "legal":
                return PolicyDecision(ESCALATE, "decision_policies.legal", "legal matters require owner")

        if action == "refund":
            return PolicyDecision(ESCALATE, "decision_policies.refund", "refunds require owner")

        if action in ("discount", "price_approval", "final_price"):
            return PolicyDecision(
                APPROVAL_REQUIRED, "decision_policies.price_approval", "final pricing is owner-only"
            )

        if risk_level == "critical":
            return PolicyDecision(ESCALATE, "risk.critical", "critical risk requires owner")
        if risk_level == "high":
            return PolicyDecision(
                APPROVAL_REQUIRED, "risk.high", "high-risk action requires approval"
            )

        return PolicyDecision(ALLOW, "policy.default", "allowed")
