"""Telegram Channel Adapter — normalizes Telegram updates into Canonical Inbound Messages."""

from __future__ import annotations

import logging
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from .base import BaseChannelAdapter

log = logging.getLogger("amancore.requirements.adapters.telegram")


class TelegramAdapter(BaseChannelAdapter):
    """Adapter for Telegram Bot webhook updates and messages."""

    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not isinstance(raw_payload, dict):
            return False

        # Telegram Update format: {"update_id": 123, "message": {"message_id": 456, "from": {"id": 789}, "text": "..."}}
        if "message" in raw_payload:
            msg = raw_payload.get("message")
            if isinstance(msg, dict) and "from" in msg and "text" in msg:
                return True

        if "external_user_id" in raw_payload and "text" in raw_payload:
            return True

        return False

    def normalize_to_canonical(
        self,
        raw_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> CanonicalInboundMessage | None:
        sender_id = ""
        msg_id = ""
        text = ""
        sender_name = None

        if "message" in raw_payload:
            msg = raw_payload["message"]
            user_info = msg.get("from") or {}
            sender_id = str(user_info.get("id", ""))
            msg_id = f"tg_{msg.get('message_id', '')}"
            text = msg.get("text", "")
            first_name = user_info.get("first_name", "")
            last_name = user_info.get("last_name", "")
            sender_name = f"{first_name} {last_name}".strip() or None
        else:
            sender_id = str(raw_payload.get("external_user_id", ""))
            msg_id = str(raw_payload.get("external_message_id", f"tg_msg_{hash(sender_id)}"))
            text = str(raw_payload.get("text", ""))
            sender_name = raw_payload.get("name")

        resolved = self.resolver.resolve_context(
            channel="telegram",
            sender_id=sender_id,
            sender_name=sender_name,
        )
        if resolved is None:
            return None

        return CanonicalInboundMessage(
            message_id=msg_id,
            conversation_id=resolved.conversation_id,
            lead_id=resolved.lead_id,
            project_id=resolved.project_id,
            channel="telegram",
            sender_id=sender_id,
            content=text,
            metadata={"sender_name": sender_name, "raw_headers": headers or {}},
        )

    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format channel-neutral response for Telegram delivery."""
        if ril_response.status != "success":
            return {
                "channel": "telegram",
                "chat_id": ril_response.lead_id,
                "status": "error",
                "error": ril_response.error,
            }

        reply_text = ""
        if ril_response.next_question:
            reply_text = f"❓ *سؤال توضيحي:*\n{ril_response.next_question}"
        elif ril_response.is_ready_for_proposal:
            reply_text = "✅ *اكتملت جميع المتطلبات الأساسية:* جاهز لتجهيز العرض الفني."
        else:
            reply_text = "📋 *تم حفظ المتطلبات بنجاح.*"

        return {
            "channel": "telegram",
            "chat_id": ril_response.lead_id,
            "text": reply_text,
            "parse_mode": "Markdown",
            "ril_summary": {
                "requirements_count": ril_response.total_requirements_count,
                "coverage_score": ril_response.coverage_score,
                "scope_version": ril_response.scope_version_number,
            },
        }
