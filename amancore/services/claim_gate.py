"""Claim Gate — deterministic. Prevents fabricated claims from being published."""

from __future__ import annotations

from dataclasses import dataclass, field

CLEAN = "clean"
FLAGGED = "flagged"
NEEDS_VERIFICATION = "needs_verification"
FORBIDDEN = "forbidden"

# Heuristic signal words that likely indicate an unapproved commercial claim.
_RISKY_KEYWORDS = [
    "guarantee", "guaranteed", "certified", "award", "results",
    "revenue", "pricing", "price:", "starting at", "% increase",
    "we have served", "clients", "testimonial", "partnership",
]


@dataclass
class ClaimDecision:
    status: str
    forbidden: list = field(default_factory=list)
    needs_verification: list = field(default_factory=list)
    policy_reference: str = ""


class ClaimGate:
    def __init__(self, brain_store):
        self.brain_store = brain_store

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def check(self, text: str) -> ClaimDecision:
        lower = (text or "").lower()
        forbidden = self.brain.get("forbidden_claims", [])
        require_verify = self.brain.get("claims_requiring_verification", [])

        found_forbidden = [c for c in forbidden if c.lower() in lower]
        if found_forbidden:
            return ClaimDecision(
                status=FORBIDDEN, forbidden=found_forbidden, policy_reference="forbidden_claims"
            )

        found_verify = [c for c in require_verify if c.lower() in lower]
        risky = [k for k in _RISKY_KEYWORDS if k in lower]
        if found_verify or risky:
            return ClaimDecision(
                status=NEEDS_VERIFICATION,
                needs_verification=found_verify or risky,
                policy_reference="claims_requiring_verification",
            )

        return ClaimDecision(status=CLEAN, policy_reference="approved_claims")
