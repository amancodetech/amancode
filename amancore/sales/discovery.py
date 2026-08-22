"""Discovery engine — consultative questions, one at a time, priority-ordered."""

from __future__ import annotations

PRIORITY = [
    "problem", "desired_outcome", "current_process", "scope", "authority",
    "budget", "timeline", "users", "integrations", "languages",
    "support_needs", "constraints",
]

TEMPLATES = {
    "problem": "What's the biggest challenge with how you currently do this?",
    "desired_outcome": "What would a successful outcome look like for you?",
    "current_process": "How do you handle this today?",
    "users": "Who will be using this system?",
    "scope": "What's the most important part of this for you?",
    "timeline": "When do you need this ready?",
    "budget": "What budget range have you set aside for this?",
    "authority": "Who will be making the final decision?",
    "constraints": "Any constraints or requirements I should know about?",
    "integrations": "What tools or systems does this need to connect with?",
    "languages": "Which languages should the solution support?",
    "support_needs": "What kind of ongoing support would you need?",
}


class DiscoveryEngine:
    def __init__(self, router=None):
        self.router = router

    def missing_fields(self, memory: dict) -> list[str]:
        facts = memory.get("facts", {})
        return [f for f in PRIORITY if f not in facts]

    def next_question(self, memory: dict) -> str | None:
        missing = self.missing_fields(memory)
        return TEMPLATES[missing[0]] if missing else None
