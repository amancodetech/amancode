"""Support response filter — stricter than the channel filter.

Blocks anything internal that must never reach a customer:
internal notes, cost figures, scores, model info, credentials, private
policies, audit data. Deterministic term-based scan.
"""

from __future__ import annotations

from ..channels.response_filter import ExternalResponseFilter, _INTERNAL_TERMS

_EXTRA_TERMS = [
    "internal notes", "internal cost", "lead score", "risk score",
    "model info", "model name", "credentials", "access token",
    "private policy", "audit data", "approval id", "business brain",
    "usage record", "token usage", "api key", "password",
    "true cost", "shadow rate", "gross margin", "cost floor",
    "minimum approved", "negotiation range", "confidence score",
]


class SupportResponseFilter(ExternalResponseFilter):
    def __init__(self):
        super().__init__()
        self._terms = list(_INTERNAL_TERMS) + _EXTRA_TERMS

    def check(self, text: str) -> dict:
        lower = (text or "").lower()
        found = [term for term in self._terms if term in lower]
        return {"allowed": not found, "found": found}

    def sanitize(self, text: str) -> str:
        clean = text or ""
        for term in self._terms:
            clean = clean.replace(term, "[internal]")
        return clean
