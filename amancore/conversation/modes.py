"""ModeManager — conversation MODE state machine (separate from CRM FSM).

Modes answer ONE question: how should the AI behave right now?

    OPENING -> NEED -> SHAPING -> COMMERCIAL -> (OFFER/NEGOTIATION/DECISION)

Transitions are evidence-based and deterministic. OFFER entry is NOT wired
here (it requires an approved pricing snapshot — P0-3); FOLLOW_UP/DECISION
are reserved identifiers for later phases.
"""

from __future__ import annotations

import re

MODES = ("OPENING", "NEED", "SHAPING", "COMMERCIAL", "OFFER",
         "NEGOTIATION", "DECISION", "FOLLOW_UP")

_AFFIRM_RE = None  # built lazily from policy data


class ModeManager:
    def __init__(self, policy):
        self.policy = policy

    # ---- lifecycle -----------------------------------------------------
    def initial_mode(self, text: str, service_category: str | None) -> str:
        """Greeting-only => OPENING; concrete request => NEED;
        direct commercial question (price/duration) => COMMERCIAL."""
        if self.policy.commercial_signal(text):
            return "COMMERCIAL"
        if service_category or self.policy.has_request_verb(text):
            return "NEED"
        return "OPENING"

    def advance(self, current: str, *, text: str, agent_result: dict,
                working_memory: dict) -> tuple[str, dict]:
        """Evidence-based transition. Returns (mode, updated_working_memory)."""
        wm = dict(working_memory or {})
        mode = current if current in MODES else "NEED"

        if mode == "OPENING" and self.policy.commercial_signal(text):
            return "COMMERCIAL", wm

        # Objections during commercial phases pull the conversation into
        # negotiation behavior (scope-before-price golden rule lives there).
        if agent_result.get("objection") and mode in ("COMMERCIAL", "OFFER"):
            wm["return_mode"] = mode
            return "NEGOTIATION", wm

        facts = (agent_result.get("qualification") or {}).get("need") is not None
        recommendation_ready = bool(agent_result.get("recommendation"))

        if mode == "OPENING":
            if wm.get("service_category") or self.policy.has_request_verb(text) \
                    or self.policy.commercial_signal(text):
                return "NEED", wm
            return mode, wm

        if mode == "NEED":
            # A structure was proposed last turn and the customer replied:
            # we are now shaping the solution together.
            if wm.get("structure_proposed"):
                return "SHAPING", {**wm, "structure_proposed": False}
            if recommendation_ready:
                return "COMMERCIAL", wm
            return mode, wm

        if mode == "SHAPING":
            if recommendation_ready:
                return "COMMERCIAL", wm
            if self.policy.commercial_signal(text) or _affirms_and_asks_price(text, self.policy):
                return "COMMERCIAL", wm
            return mode, wm

        if mode in ("COMMERCIAL", "NEGOTIATION", "OFFER", "DECISION"):
            return mode, wm
        return mode, wm

    # ---- persistence helpers ------------------------------------------
    @staticmethod
    def load(working_memory_json) -> dict:
        if isinstance(working_memory_json, dict):
            return dict(working_memory_json)
        return {}

    @staticmethod
    def hydrate(wm: dict, *, industry: str | None, service_category: str | None,
                structure_proposed: bool | None = None,
                question_field: str | None = None) -> dict:
        out = dict(wm)
        if industry:
            out.setdefault("industry", industry)
        if service_category:
            out.setdefault("service_category", service_category)
        if structure_proposed is not None:
            out["structure_proposed"] = structure_proposed
        if question_field:
            out["last_question_field"] = question_field
        return out


def _affirms_and_asks_price(text: str, policy) -> bool:  # pragma: no cover - helper
    return bool(re.search(r"(سعر|price|harga)", text or "", re.I)) and policy.affirmation(text)
