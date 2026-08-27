"""Objection handling skill — golden rule: reduce scope before price.

P1-final §4: the Business Brain ``objections`` section is THE single
taxonomy of record (12 rows). This skill reads ids/signals/strategy/limits
from the Brain; it owns NO keyword lists and NO per-objection canned text.
Responses are produced from ONE canonical ladder implementation:

    value -> scope-reduce -> phased -> smallest-tier

The response DICT contract is unchanged for existing consumers
(intent/clarification/value_response/scope_reduction/
alternative_offer/escalation_condition).
"""

from __future__ import annotations

_LADDER: dict[str, dict[str, str]] = {
    "value": {
        "clarification": ("What single outcome matters most to you right "
                          "now?"),
        "value_response": ("Let's anchor this in your own stated business "
                           "outcome rather than the deliverable itself."),
        "scope_reduction": "",
        "alternative_offer": "",
    },
    "scope-reduce": {
        "clarification": ("Which part would you like to remove or start "
                          "without?"),
        "value_response": ("The price reflects an integrated system, not "
                           "page count — trimming scope keeps the core."),
        "scope_reduction": ("We can start with the essential part now and "
                            "add the rest later."),
        "alternative_offer": "Business Presence Starter",
    },
    "phased": {
        "clarification": ("What milestone or date are you working "
                          "toward?"),
        "value_response": ("A real phase-1 launch gives value early; we "
                           "sequence the rest after it proves out."),
        "scope_reduction": ("Prioritize the must-have slice for the first "
                            "phase."),
        "alternative_offer": "",
    },
    "smallest-tier": {
        "clarification": ("Would starting on our smallest official tier "
                          "work for you?"),
        "value_response": ("The entry tier covers the core need with room "
                           "to grow — that is where I'd begin."),
        "scope_reduction": ("Scope stays within the tier's essentials until "
                            "you ask to grow."),
        "alternative_offer": "Business Presence Starter",
    },
}


class ObjectionHandlingSkill:
    """Brain-driven classifier + ladder-bound responder."""

    def __init__(self, brain_store, router=None):
        self.brain_store = brain_store
        self.router = router

    # ---- taxonomy access (single source of truth) ------------------------
    def _rows(self) -> list[dict]:
        try:
            _, brain = self.brain_store.current()
        except Exception:  # noqa: BLE001 — brain outage degrades to silent
            return []
        rows = brain.get("objections") or []
        return rows if isinstance(rows, list) else []

    def taxonomy_ids(self) -> list[str]:
        return [r.get("id") for r in self._rows()]

    def classify(self, message: str) -> str | None:
        low = f" {(message or '').lower()} "
        for row in self._rows():
            signals = row.get("signals") or {}
            words = list(signals.get("en") or []) + \
                list(signals.get("ar") or [])
            for w in words:
                if w and w.lower() in low:
                    return row["id"]
        return None

    def handle(self, objection_id: str, brain: dict | None = None) -> dict:
        rows = []
        try:
            _, cur = self.brain_store.current()
            rows = cur.get("objections") or []
        except Exception:  # noqa: BLE001
            rows = []
        if brain and isinstance(brain, dict):
            rows = brain.get("objections") or rows
        row = next((r for r in rows if r.get("id") == objection_id), None)
        if not row:
            return {
                "intent": "unknown",
                "clarification": "Can you tell me more about that?",
                "value_response": "", "scope_reduction": "",
                "alternative_offer": "", "escalation_condition": "",
            }
        strategy = str(row.get("recommended_strategy") or "value")
        tmpl = _LADDER.get(strategy, _LADDER["value"])
        return {
            "intent": row.get("intent") or "unknown",
            "clarification": tmpl["clarification"],
            "value_response": tmpl["value_response"],
            "scope_reduction": tmpl["scope_reduction"],
            "alternative_offer": tmpl["alternative_offer"],
            "escalation_condition": str(
                row.get("owner_escalation_requirement") or ""),
        }
