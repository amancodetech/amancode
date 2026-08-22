"""External response filter — prevents internal data leakage to customers."""

from __future__ import annotations

_INTERNAL_TERMS = [
    "true_cost", "true cost", "shadow_rate", "shadow rate", "lead_score", "lead score",
    "risk_score", "risk score", "confidence", "founder_cost", "cost_floor",
    "minimum_approved", "negotiation_range", "pricing_policy_version",
    "internal notes", "internal cost", "model name", "system prompt",
]


class ExternalResponseFilter:
    def check(self, text: str) -> dict:
        lower = (text or "").lower()
        found = [term for term in _INTERNAL_TERMS if term in lower]
        return {"allowed": not found, "found": found}

    def sanitize(self, text: str) -> str:
        clean = text
        for term in _INTERNAL_TERMS:
            clean = clean.replace(term, "[internal]")
        return clean
