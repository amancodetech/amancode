"""Objection handling skill — golden rule: reduce scope before price."""

from __future__ import annotations

_KEYWORDS = {
    "price_high": ["expensive", "too pricey", "price", "cost", "mahal", "سعر", "غالي", "harga", "biaya"],
    "need_think": ["think about", "need to think", "consider", "أفكر", "pikir"],
    "have_developer": ["have a developer", "developer", "مطور", "already have"],
    "want_simpler": ["simpler", "simple", "أبسط", "بسيط", "sederhana"],
    "want_discount": ["discount", "خصم", "diskon"],
    "need_faster": ["faster", "asap", "أسرع", "cepat"],
    "see_value": ["value", "worth", "قيمة", "nilai"],
    "just_prices": ["just send", "price list", "prices", "أسعار", "daftar harga"],
}

_RESPONSES = {
    "price_high": {
        "intent": "price_sensitivity",
        "clarification": "Which part of the scope matters most to you right now?",
        "value_response": "The price reflects the full integrated system (website + WhatsApp + automation), not just pages.",
        "scope_reduction": "We can start with the essential part and add the rest later.",
        "alternative_offer": "Business Presence Starter",
        "escalation_condition": "request below minimum approved price",
    },
    "need_think": {
        "intent": "hesitation",
        "clarification": "What's the main thing you need to be sure about?",
        "value_response": "Happy to clarify any part of the approach.",
        "scope_reduction": "",
        "alternative_offer": "",
        "escalation_condition": "",
    },
    "have_developer": {
        "intent": "comparison",
        "clarification": "What's missing with your current developer?",
        "value_response": "We complement by delivering an integrated multilingual system end-to-end.",
        "scope_reduction": "",
        "alternative_offer": "",
        "escalation_condition": "",
    },
    "want_simpler": {
        "intent": "scope",
        "clarification": "Which part would you like to remove to keep it simple?",
        "value_response": "We can reduce the scope while keeping the core result.",
        "scope_reduction": "Reduce to a single-page presence + WhatsApp.",
        "alternative_offer": "Business Presence Starter",
        "escalation_condition": "",
    },
    "want_discount": {
        "intent": "price",
        "clarification": "Are you open to adjusting the scope instead of the price?",
        "value_response": "We keep pricing fair and value-based.",
        "scope_reduction": "Remove non-essential features to lower cost.",
        "alternative_offer": "Smaller package",
        "escalation_condition": "any discount decision (owner-only)",
    },
    "need_faster": {
        "intent": "timeline",
        "clarification": "What's the deadline you're working toward?",
        "value_response": "We'll confirm feasibility against our delivery capacity.",
        "scope_reduction": "Prioritize the must-have for launch.",
        "alternative_offer": "",
        "escalation_condition": "impossible deadline",
    },
    "see_value": {
        "intent": "value",
        "clarification": "What outcome would make this worth it for you?",
        "value_response": "We focus on the business result, not just the deliverable.",
        "scope_reduction": "",
        "alternative_offer": "",
        "escalation_condition": "",
    },
    "just_prices": {
        "intent": "shopping",
        "clarification": "I can share a starting range, but the final scope determines the exact price.",
        "value_response": "Every project is scoped to your needs.",
        "scope_reduction": "",
        "alternative_offer": "",
        "escalation_condition": "final price requires owner",
    },
}


class ObjectionHandlingSkill:
    def __init__(self, brain_store, router=None):
        self.brain_store = brain_store
        self.router = router

    def classify(self, message: str) -> str | None:
        lower = (message or "").lower()
        for oid, words in _KEYWORDS.items():
            if any(w in lower for w in words):
                return oid
        return None

    def handle(self, objection_id: str, brain: dict) -> dict:
        return _RESPONSES.get(objection_id, {
            "intent": "unknown",
            "clarification": "Can you tell me more about that?",
            "value_response": "",
            "scope_reduction": "",
            "alternative_offer": "",
            "escalation_condition": "",
        })
