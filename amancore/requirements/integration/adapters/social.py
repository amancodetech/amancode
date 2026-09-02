"""Social Channel Adapter — supports TikTok and other Social Media inquiries."""

from __future__ import annotations

import logging
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from .base import BaseChannelAdapter

log = logging.getLogger("amancore.requirements.adapters.social")


class SocialAdapter(BaseChannelAdapter):
    """Adapter for TikTok direct inquiries and social channels."""

    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not isinstance(raw_payload, dict):
            return False

        # Support TikTok webhook or bridge event
        if "tiktok_user_id" in raw_payload or "author_id" in raw_payload or "external_user_id" in raw_payload:
            return bool(raw_payload.get("text") or raw_payload.get("comment") or raw_payload.get("message"))

        return False

    def normalize_to_canonical(
        self,
        raw_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> CanonicalInboundMessage | None:
        channel_name = str(raw_payload.get("channel") or "tiktok").lower()
        sender_id = str(
            raw_payload.get("tiktok_user_id")
            or raw_payload.get("author_id")
            or raw_payload.get("external_user_id")
            or ""
        )
        msg_id = str(raw_payload.get("event_id") or raw_payload.get("comment_id") or f"social_{hash(sender_id)}")
        text = str(raw_payload.get("text") or raw_payload.get("comment") or raw_payload.get("message") or "")
        sender_name = raw_payload.get("nickname") or raw_payload.get("name")

        resolved = self.resolver.resolve_context(
            channel=channel_name,
            sender_id=sender_id,
            sender_name=sender_name,
        )
        if resolved is None or resolved.status != "resolved":
            return None

        return CanonicalInboundMessage(
            provider_message_id=msg_id,
            conversation_id=resolved.conversation_id,
            lead_id=resolved.lead_id,
            project_id=resolved.project_id,
            channel=channel_name,
            provider=channel_name,
            external_user_id=sender_id,
            message_text=text,
            metadata={"sender_name": sender_name, "raw_headers": headers or {}},
        )

    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format response for TikTok DM or comment reply."""
        if ril_response.status != "success":
            return {"status": "error", "error": ril_response.error}

        reply_text = ""
        if ril_response.next_question:
            reply_text = ril_response.next_question
        elif ril_response.is_ready_for_proposal:
            reply_text = "شكراً لاهتمامك! تم حصر المتطلبات وسنتواصل معك لتقديم العرض."
        else:
            reply_text = "أهلاً بك! تم استلام استفسارك وسنتابع معك لتحديد التفاصيل."

        return {
            "status": "success",
            "reply_text": reply_text,
            "lead_id": ril_response.lead_id,
            "ril_summary": {
                "requirements_count": ril_response.total_requirements_count,
                "coverage_score": ril_response.coverage_score,
            },
        }
