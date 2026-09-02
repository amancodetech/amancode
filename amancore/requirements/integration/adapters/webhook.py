"""External Webhook Ingestion Boundary — HMAC signature validation, timestamp verification & size bounds."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from .base import BaseChannelAdapter

log = logging.getLogger("amancore.requirements.adapters.webhook")


class WebhookAdapter(BaseChannelAdapter):
    """Secure ingestion adapter for external partner/API webhooks."""

    def __init__(
        self,
        resolver,
        ril_service,
        secret_key: str | None = None,
        max_payload_bytes: int = 1024 * 1024,  # 1MB
        replay_window_seconds: int = 300,
    ):
        super().__init__(resolver, ril_service)
        self.secret_key = secret_key or "default_test_secret_key"
        self.max_payload_bytes = max_payload_bytes
        self.replay_window_seconds = replay_window_seconds

    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        if not isinstance(raw_payload, dict):
            return False

        headers = headers or {}
        # 1. Payload size check
        payload_bytes = len(json.dumps(raw_payload).encode("utf-8"))
        if payload_bytes > self.max_payload_bytes:
            log.warning("webhook.rejected reason=payload_too_large size=%d", payload_bytes)
            return False

        # 2. Timestamp check (replay protection)
        req_timestamp = headers.get("X-Timestamp") or headers.get("x-timestamp")
        if req_timestamp:
            try:
                ts = float(req_timestamp)
                now = time.time()
                if abs(now - ts) > self.replay_window_seconds:
                    log.warning("webhook.rejected reason=timestamp_expired diff=%f", abs(now - ts))
                    return False
            except (ValueError, TypeError):
                return False

        # 3. HMAC Signature check if provided
        sig = headers.get("X-Signature") or headers.get("x-signature")
        if sig and self.secret_key:
            expected = hmac.new(
                self.secret_key.encode("utf-8"),
                json.dumps(raw_payload, sort_keys=True).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig, expected):
                log.warning("webhook.rejected reason=invalid_signature")
                return False

        # 4. Mandatory content checks
        return bool(raw_payload.get("customer_id") or raw_payload.get("external_user_id"))

    def normalize_to_canonical(
        self,
        raw_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> CanonicalInboundMessage | None:
        sender_id = str(raw_payload.get("customer_id") or raw_payload.get("external_user_id") or "")
        event_id = str(raw_payload.get("event_id") or f"webhook_evt_{hash(sender_id + str(time.time()))}")
        text = str(raw_payload.get("text") or raw_payload.get("message") or raw_payload.get("content") or "")
        channel_name = str(raw_payload.get("channel") or "webhook")

        resolved = self.resolver.resolve_context(
            channel=channel_name,
            sender_id=sender_id,
            sender_name=raw_payload.get("name"),
        )
        if resolved is None:
            return None

        return CanonicalInboundMessage(
            message_id=event_id,
            conversation_id=resolved.conversation_id,
            lead_id=resolved.lead_id,
            project_id=resolved.project_id,
            channel=channel_name,
            sender_id=sender_id,
            content=text,
            metadata={
                "event_id": event_id,
                "webhook_metadata": raw_payload.get("metadata", {}),
            },
        )

    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format channel-neutral response for external webhook response."""
        return {
            "status": ril_response.status,
            "lead_id": ril_response.lead_id,
            "project_id": ril_response.project_id,
            "new_requirements_count": ril_response.new_requirements_count,
            "total_requirements_count": ril_response.total_requirements_count,
            "active_decisions": ril_response.active_decisions,
            "conflicts_count": ril_response.conflicts_count,
            "coverage_score": ril_response.coverage_score,
            "is_ready_for_proposal": ril_response.is_ready_for_proposal,
            "next_question": ril_response.next_question,
            "scope_version_number": ril_response.scope_version_number,
            "processing_duration_ms": ril_response.processing_duration_ms,
            "error": ril_response.error,
        }
