"""Human takeover — conversation modes. AI stops sending when a human is active."""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..services.events import CanonicalEvent

MODES = ["AI_ACTIVE", "HUMAN_REQUESTED", "HUMAN_ACTIVE", "AI_RESUMED", "CLOSED"]


ALL_CHANNELS = ["whatsapp", "facebook", "instagram", "tiktok", "youtube", "website"]


class HandoverService:
    def __init__(self, crm, dispatcher=None):
        self.crm = crm
        self.dispatcher = dispatcher

    def is_channel_ai_enabled(self, channel: str) -> bool:
        ch = (channel or "whatsapp").lower()
        try:
            row = self.crm.db.execute(
                "SELECT enabled FROM channel_ai_settings WHERE channel=?", (ch,)
            ).fetchone()
            if row is not None:
                return bool(row["enabled"] if isinstance(row, dict) or hasattr(row, "__getitem__") else row[0])
        except Exception:  # noqa: BLE001
            pass
        return True

    def set_channel_ai(self, channel: str, enabled: bool) -> bool:
        ch = (channel or "whatsapp").lower()
        now = utcnow()
        try:
            self.crm.db.execute(
                "INSERT INTO channel_ai_settings (channel, enabled, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(channel) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
                (ch, 1 if enabled else 0, now),
            )
            self.crm.db.commit()
            if self.dispatcher is not None:
                self.dispatcher.publish(
                    CanonicalEvent(
                        event_id=new_id(),
                        event_type="handover.channel_ai_toggled",
                        timestamp=now,
                        source="handover",
                        actor_type="owner",
                        payload={"channel": ch, "enabled": enabled},
                    )
                )
            return enabled
        except Exception as e:  # noqa: BLE001
            return enabled

    def get_all_channel_ai_status(self) -> dict[str, bool]:
        status = {c: True for c in ALL_CHANNELS}
        try:
            rows = self.crm.db.execute("SELECT channel, enabled FROM channel_ai_settings").fetchall()
            for r in rows:
                ch = r["channel"] if isinstance(r, dict) or hasattr(r, "__getitem__") else r[0]
                en = r["enabled"] if isinstance(r, dict) or hasattr(r, "__getitem__") else r[1]
                status[ch] = bool(en)
        except Exception:  # noqa: BLE001
            pass
        return status

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

    def can_send_ai(self, lead_id: str, channel: str = "whatsapp") -> bool:
        if not self.is_channel_ai_enabled(channel):
            return False
        return self.get_mode(lead_id) in ("AI_ACTIVE", "AI_RESUMED")
