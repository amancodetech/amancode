"""Content approval — claim gate + risk classification + approval workflow."""

from __future__ import annotations

from .claim_gate import FORBIDDEN, NEEDS_VERIFICATION, ClaimGate

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

_CRITICAL_KEYWORDS = ["legal", "regulatory", "medical", "financial guarantee", "guaranteed return", "investment", "refund policy"]
_HIGH_KEYWORDS = ["guarantee", "guaranteed", "pricing", "price", "$", "discount", "competitor", "comparison", "results", "testimonial", "our clients", "our customers", "starting at", "case study"]
_MEDIUM_KEYWORDS = ["our service", "our package", "we offer", "our offer", "our website", "our app", "our system", "our automation", "our solution", "book a", "get a quote", "hire us"]


class ContentApprovalService:
    def __init__(self, brain_store, approvals=None, audit=None):
        self.claim_gate = ClaimGate(brain_store)
        self.brain_store = brain_store
        self.approvals = approvals
        self.audit = audit

    def classify_risk(self, text: str, content_type: str = "") -> str:
        lower = (text or "").lower()
        if any(k in lower for k in _CRITICAL_KEYWORDS):
            return CRITICAL
        if any(k in lower for k in _HIGH_KEYWORDS):
            return HIGH
        if any(k in lower for k in _MEDIUM_KEYWORDS):
            return MEDIUM
        return LOW

    def evaluate(self, content: dict) -> dict:
        """Return {status, claim_status, risk_level, needs_owner, approval_id}."""
        text = content.get("body", "")
        claim = self.claim_gate.check(text)
        if claim.status == FORBIDDEN:
            return self._result("rejected", claim.status, LOW, False, None, "forbidden claim")

        risk = self.classify_risk(text, content.get("content_type", ""))

        if risk in (CRITICAL, HIGH):
            approval_id = self._request_approval(content, risk, claim)
            return self._result("review", claim.status, risk, True, approval_id, f"{risk} risk")

        if risk == MEDIUM:
            return self._result("review", claim.status, risk, False, None, "medium risk (human review)")

        if claim.status == NEEDS_VERIFICATION:
            return self._result("review", claim.status, risk, False, None, "claim needs verification")

        return self._result("approved", claim.status, risk, False, None, "low risk + clean claims")

    def _request_approval(self, content: dict, risk: str, claim) -> str | None:
        if self.approvals is None:
            return None
        return self.approvals.create_approval_request(
            type_="content_approval",
            requested_by="content_agent",
            risk_level=risk,
            reason=f"content approval required: {claim.status}",
            payload={"content_id": content.get("content_id"), "title": content.get("title")},
            policy_reference="content_policy",
        )

    @staticmethod
    def _result(status, claim_status, risk_level, needs_owner, approval_id, reason) -> dict:
        return {
            "status": status,
            "claim_status": claim_status,
            "risk_level": risk_level,
            "needs_owner": needs_owner,
            "approval_id": approval_id,
            "reason": reason,
        }
