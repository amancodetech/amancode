"""Human handoff — detect + request (no external send; emits event only)."""

from __future__ import annotations

from ..ids import new_id, utcnow

_HANDOFF_KEYWORDS = {
    "human_requested": ["talk to a human", "speak to someone", "human", "إنسان", "بشري", "orang"],
    "angry_customer": ["angry", "furious", "complaint", "شكوى", "غاضب", "marah"],
    "legal": ["legal", "lawyer", "contract", "قانون", "محام"],
    "refund": ["refund", "استرداد", "ارجاع"],
    "impossible_deadline": ["impossible", "by tomorrow", "today by", "مستحيل", "غدًا", "اليوم"],
}


class HandoffService:
    def __init__(self, dispatcher=None):
        self.dispatcher = dispatcher

    def detect(self, message: str) -> str | None:
        lower = (message or "").lower()
        for reason, words in _HANDOFF_KEYWORDS.items():
            if any(w in lower for w in words):
                return reason
        return None

    def request(
        self,
        lead: dict,
        conversation: dict,
        reason: str,
        urgency: str = "normal",
        summary: str = "",
        recommended_action: str = "",
        unresolved_questions: list | None = None,
        lead_score: int | None = None,
        risk_level: str = "medium",
    ) -> dict:
        handoff = {
            "id": new_id(),
            "lead_id": lead.get("lead_id"),
            "conversation_id": conversation.get("conversation_id"),
            "reason": reason,
            "urgency": urgency,
            "summary": summary or conversation.get("summary", ""),
            "recommended_action": recommended_action,
            "unresolved_questions": unresolved_questions or [],
            "lead_score": lead_score,
            "risk_level": risk_level,
            "created_at": utcnow(),
        }
        if self.dispatcher is not None:
            from ..services.events import CanonicalEvent

            self.dispatcher.publish(
                CanonicalEvent(
                    event_id=new_id(),
                    event_type="sales.handoff_requested",
                    timestamp=utcnow(),
                    source="sales",
                    actor_type="agent",
                    actor_id="sales",
                    risk_level=risk_level,
                    payload={"handoff_id": handoff["id"], "reason": reason},
                )
            )
        return handoff
