"""Outreach Policy Foundation — deterministic. No send tool wired in Phase 3B."""

from __future__ import annotations

from dataclasses import dataclass, field

ALLOW = "allow"
DENY = "deny"
APPROVAL_REQUIRED = "approval_required"


@dataclass
class OutreachDecision:
    action: str
    reasons: list = field(default_factory=list)


class OutreachPolicy:
    def __init__(self, brain_store, rate_limit: int = 20):
        self.brain_store = brain_store
        self.rate_limit = rate_limit

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def evaluate(
        self,
        lead: dict,
        previous_contact: bool = False,
        sent_today: int = 0,
    ) -> OutreachDecision:
        reasons: list[str] = []

        # targeting: must have meaningful business presence
        if not lead.get("company") and not lead.get("website"):
            return OutreachDecision(DENY, ["no meaningful business presence (missing company/website)"])

        # opt-out
        if lead.get("opt_out"):
            return OutreachDecision(DENY, ["lead opted out"])

        # market must be supported
        supported = set(self.brain.get("market_profiles", {}).keys())
        market = lead.get("market")
        if market and market not in supported:
            return OutreachDecision(DENY, [f"unsupported market: {market}"])

        # previous contact
        if previous_contact:
            return OutreachDecision(DENY, ["already contacted"])

        # rate limit
        if sent_today >= self.rate_limit:
            return OutreachDecision(DENY, [f"rate limit reached ({sent_today}/{self.rate_limit})"])

        # personalization: need some ICP signal
        if not lead.get("industry") and not lead.get("fit_signals") and not lead.get("likely_needs"):
            return OutreachDecision(APPROVAL_REQUIRED, ["insufficient personalization signals"])

        return OutreachDecision(ALLOW, [])
