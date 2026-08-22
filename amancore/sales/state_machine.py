"""Sales state machine — strict transitions (no new→won without override)."""

from __future__ import annotations

from ..errors import AmanCoreError

STATES = [
    "new", "contacted", "engaged", "discovery", "qualification",
    "offer_recommended", "proposal", "negotiation", "awaiting_decision",
    "won", "lost", "onboarding",
]

TRANSITIONS: dict[str, dict[str, str]] = {
    "new": {"first_message": "contacted"},
    "contacted": {"message": "engaged"},
    "engaged": {"discovery": "discovery"},
    "discovery": {"qualified": "qualification", "message": "discovery"},
    "qualification": {"recommended": "offer_recommended"},
    "offer_recommended": {"proposal": "proposal", "lost": "lost"},
    "proposal": {"negotiation": "negotiation", "won": "won", "lost": "lost"},
    "negotiation": {"awaiting": "awaiting_decision", "won": "won", "lost": "lost"},
    "awaiting_decision": {"won": "won", "lost": "lost"},
    "won": {"onboarded": "onboarding"},
    "lost": {},
    "onboarding": {},
}

# owner-only overrides (used with owner_override=True)
OWNER_OVERRIDES = {"won", "lost"}


class InvalidTransition(AmanCoreError):
    pass


def transition(current: str, event: str, owner_override: bool = False) -> str:
    if current not in TRANSITIONS:
        raise InvalidTransition(f"unknown state: {current}")
    allowed = TRANSITIONS[current]
    if event in allowed:
        return allowed[event]
    if owner_override and event in OWNER_OVERRIDES:
        return event
    raise InvalidTransition(f"invalid transition {current} -> {event}")


def can_transition(current: str, event: str) -> bool:
    return current in TRANSITIONS and event in TRANSITIONS[current]
