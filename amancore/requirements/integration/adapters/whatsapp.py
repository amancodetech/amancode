"""WhatsApp Channel Adapter — normalizes WhatsApp webhooks into Canonical Inbound Messages."""

from __future__ import annotations

import logging
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from .base import BaseChannelAdapter

log = logging.getLogger("amancore.requirements.adapters.whatsapp")


class WhatsAppAdapter(BaseChannelAdapter):
    """Adapter for WhatsApp Business Cloud API and local Meta Bridge payloads."""

    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not isinstance(raw_payload, dict):
            return False

        # 1. Standard Meta Cloud API format
        if "entry" in raw_payload:
            entries = raw_payload.get("entry") or []
            if not entries or not isinstance(entries, list):
                return False
            changes = entries[0].get("changes") or []
            if not changes or not isinstance(changes, list):
                return False
            val = changes[0].get("value") or {}
            return bool(val.get("messages"))

        # 2. Simplified Bridge format
        if "from" in raw_payload and "body" in raw_payload:
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

        # Format 1: Cloud API
        if "entry" in raw_payload:
            val = raw_payload["entry"][0]["changes"][0]["value"]
            msg = val["messages"][0]
            sender_id = msg.get("from", "")
            msg_id = msg.get("id", "")
            text = msg.get("text", {}).get("body", "")
            contacts = val.get("contacts") or []
            if contacts:
                sender_name = contacts[0].get("profile", {}).get("name")

        # Format 2: Bridge format
        elif "from" in raw_payload:
            sender_id = raw_payload.get("from", "")
            msg_id = raw_payload.get("id", f"wa_msg_{hash(sender_id + raw_payload.get('body', ''))}")
            text = raw_payload.get("body", "")
            sender_name = raw_payload.get("name")

        # Format 3: Generic canonical
        else:
            sender_id = raw_payload.get("external_user_id", "")
            msg_id = raw_payload.get("external_message_id", f"wa_msg_{hash(sender_id)}")
            text = raw_payload.get("text", "")
            sender_name = raw_payload.get("name")

        # Resolve trusted lead & project
        resolved = self.resolver.resolve_context(
            channel="whatsapp",
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
            channel="whatsapp",
            sender_id=sender_id,
            content=text,
            metadata={"sender_name": sender_name, "raw_headers": headers or {}},
        )

    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format channel-neutral response for WhatsApp delivery."""
        if ril_response.status != "success":
            return {
                "channel": "whatsapp",
                "recipient": ril_response.lead_id,
                "status": "error",
                "error": ril_response.error,
            }

        reply_text = ""
        if ril_response.next_question:
            reply_text = ril_response.next_question
        elif ril_response.is_ready_for_proposal:
            reply_text = "شكراً لك، اكتملت جميع التفاصيل الأساسية لمتطلبات مشروعك وسنقوم بتجهيز العرض الفني المناسب."
        else:
            reply_text = "تم تسجيل متطلباتك بنجاح وسنتابع معك باقي التفاصيل."

        return {
            "channel": "whatsapp",
            "recipient": ril_response.lead_id,
            "messaging_product": "whatsapp",
            "text": {"body": reply_text},
            "ril_summary": {
                "requirements_count": ril_response.total_requirements_count,
                "coverage_score": ril_response.coverage_score,
                "scope_version": ril_response.scope_version_number,
            },
        }
