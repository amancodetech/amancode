"""Qualification engine — BANT-derived, budget alone never disqualifies."""

from __future__ import annotations

from .discovery import PRIORITY

_REQUIRED_FOR_READINESS = ["problem", "desired_outcome", "authority", "budget", "timeline"]


class QualificationEngine:
    def qualify(self, memory: dict, lead: dict, fit: dict, engagement: int = 0) -> dict:
        facts = memory.get("facts", {})
        missing = [f for f in PRIORITY if f not in facts]
        readiness = all(f in facts for f in _REQUIRED_FOR_READINESS)
        timeline = str(facts.get("timeline", "")).lower()
        urgency = (
            "high" if any(k in timeline for k in ("asap", "urgent", "مستعجل", "segera")) else
            ("stated" if facts.get("timeline") else "")
        )
        clarity = "high" if readiness else ("medium" if facts.get("problem") else "low")
        return {
            "need": facts.get("problem"),
            "outcome": facts.get("desired_outcome"),
            "current_process": facts.get("current_process"),
            "users": facts.get("users"),
            "scope": facts.get("scope"),
            "authority": facts.get("authority"),
            "urgency": urgency,
            "budget": facts.get("budget"),
            "timeline": facts.get("timeline"),
            "fit": fit,
            "clarity": clarity,
            "decision_readiness": readiness,
            "missing_information": missing,
            "engagement": engagement,
            "confidence": round(sum(1 for f in PRIORITY if f in facts) / len(PRIORITY), 2),
        }
