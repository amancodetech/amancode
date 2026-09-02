"""Meta Channel Adapter — supports Facebook Messenger and Instagram DMs."""

from __future__ import annotations

import logging
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from .base import BaseChannelAdapter

log = logging.getLogger("amancore.requirements.adapters.meta")


class MetaAdapter(BaseChannelAdapter):
    """Adapter for Meta Graph API & Local Bridge (Facebook Messenger and Instagram DM)."""

    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not isinstance(raw_payload, dict):
            return False

        # 1. Standard Meta Graph Webhook format: {"object": "page"|"instagram", "entry": [...]}
        if "entry" in raw_payload:
            entries = raw_payload.get("entry") or []
            if not entries or not isinstance(entries, list):
                return False
            messaging = entries[0].get("messaging") or []
            if messaging and isinstance(messaging, list):
                msg = messaging[0].get("message")
                return bool(msg and "text" in msg)
            changes = entries[0].get("changes") or []
            if changes and isinstance(changes, list):
                val = changes[0].get("value") or {}
                return bool(val.get("messages") or val.get("message"))

        # 2. Bridge format: {"channel": "facebook"|"instagram", "from": "...", "body": "..."}
        if "from" in raw_payload and ("body" in raw_payload or "text" in raw_payload):
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
        channel_name = raw_payload.get("channel") or ("instagram" if raw_payload.get("object") == "instagram" else "facebook")

        # Format 1: Meta Graph API messaging format
        if "entry" in raw_payload:
            entry = raw_payload["entry"][0]
            if "messaging" in entry:
                msg_item = entry["messaging"][0]
                sender_id = str(msg_item.get("sender", {}).get("id", ""))
                msg_id = str(msg_item.get("message", {}).get("mid", f"meta_mid_{hash(sender_id)}"))
                text = str(msg_item.get("message", {}).get("text", ""))
            elif "changes" in entry:
                val = entry["changes"][0].get("value", {})
                sender_id = str(val.get("from", {}).get("id") or val.get("sender", {}).get("id") or "")
                msg_id = str(val.get("id") or f"meta_mid_{hash(sender_id)}")
                text = str(val.get("message") or val.get("text", ""))

        # Format 2: Bridge format
        elif "from" in raw_payload:
            sender_id = str(raw_payload.get("from", ""))
            msg_id = str(raw_payload.get("id", f"meta_bridge_mid_{hash(sender_id)}"))
            text = str(raw_payload.get("body") or raw_payload.get("text", ""))
            sender_name = raw_payload.get("name")
        else:
            sender_id = str(raw_payload.get("external_user_id", ""))
            msg_id = str(raw_payload.get("external_message_id", f"meta_msg_{hash(sender_id)}"))
            text = str(raw_payload.get("text", ""))
            sender_name = raw_payload.get("name")

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
            provider="meta",
            external_user_id=sender_id,
            message_text=text,
            metadata={"sender_name": sender_name, "raw_headers": headers or {}},
        )

    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format channel-neutral response for Facebook/Instagram delivery."""
        if ril_response.status != "success":
            return {
                "recipient": {"id": ril_response.lead_id},
                "status": "error",
                "error": ril_response.error,
            }

        reply_text = ""
        if ril_response.next_question:
            reply_text = ril_response.next_question
        elif ril_response.is_ready_for_proposal:
            reply_text = "شكراً لتواصلك، اكتملت جميع المتطلبات الأساسية لمشروعك وسنزودك بالعرض الفني المناسب."
        else:
            reply_text = "تم تسجيل متطلباتك وسنتابع معك لتأكيد التفاصيل."

        return {
            "recipient": {"id": ril_response.lead_id},
            "message": {"text": reply_text},
            "ril_summary": {
                "requirements_count": ril_response.total_requirements_count,
                "coverage_score": ril_response.coverage_score,
                "scope_version": ril_response.scope_version_number,
            },
        }
