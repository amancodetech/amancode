"""Human takeover — conversation modes. AI stops sending when a human is active."""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..services.events import CanonicalEvent

MODES = ["AI_ACTIVE", "HUMAN_REQUESTED", "HUMAN_ACTIVE", "AI_RESUMED", "CLOSED"]


class HandoverService:
    def __init__(self, crm, dispatcher=None):
        self.crm = crm
        self.dispatcher = dispatcher

    def get_mode(self, lead_id: str) -> str:
        conv = self.crm.get_conversation_for_lead(lead_id)
        return (conv or {}).get("mode") or "AI_ACTIVE"

    def set_mode(self, lead_id: str, mode: str) -> str:
        if mode not in MODES:
            raise ValueError(f"invalid mode: {mode}")
        conv = self.crm.get_conversation_for_lead(lead_id)
        if conv is None:
            cid = self.crm.append_conversation(lead_id, "internal", mode=mode, current_state="new")
            conv = self.crm.get_conversation(cid)
        else:
            self.crm.update_conversation(conv["conversation_id"], mode=mode)
        if self.dispatcher is not None:
            self.dispatcher.publish(
                CanonicalEvent(
                    event_id=new_id(),
                    event_type="handover.mode_changed",
                    timestamp=utcnow(),
                    source="handover",
                    actor_type="system",
                    payload={"lead_id": lead_id, "mode": mode},
                )
            )
        return mode

    def request_human(self, lead_id: str) -> str:
        if self.get_mode(lead_id) == "HUMAN_ACTIVE":
            return "HUMAN_ACTIVE"
        return self.set_mode(lead_id, "HUMAN_REQUESTED")

    def activate_human(self, lead_id: str) -> str:
        return self.set_mode(lead_id, "HUMAN_ACTIVE")

    def resume_ai(self, lead_id: str) -> str:
        return self.set_mode(lead_id, "AI_RESUMED")

    def can_send_ai(self, lead_id: str) -> bool:
        return self.get_mode(lead_id) in ("AI_ACTIVE", "AI_RESUMED")
