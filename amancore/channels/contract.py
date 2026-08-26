"""Channel adapter contract — channels are transport, never business logic.

The adapter owns: provider API/auth/payloads/webhook verification/error
mapping/media mechanics/capabilities. It must NEVER own sales decisions,
pricing, CRM rules, compliance policy, or AI authority.
"""

from __future__ import annotations

from .canonical import ChannelCapabilities, TEXT_ONLY


class ChannelAdapter:
    channel = "generic"

    def send(self, recipient: str, message_type: str, payload) -> dict:
        raise NotImplementedError

    def receive_webhook(self, body, headers=None) -> list:
        raise NotImplementedError

    def verify_webhook(self, **params) -> dict:
        raise NotImplementedError

    # ---- contract surface (each method has a real core consumer) -------

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        """Fail-closed by default: a channel that enables signature_required
        MUST implement real verification (loud misconfiguration > silent bypass)."""
        raise NotImplementedError(
            f"adapter {type(self).__name__} does not implement verify_signature "
            "but its config enables signature_required")

    def capabilities(self) -> ChannelCapabilities:
        """Conservative default: text only."""
        return TEXT_ONLY

    def normalize_recipient(self, raw) -> str:
        """Provider addressing format (e.g. E.164 digits). Default: opaque passthrough."""
        return str(raw or "")

    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        """Map a provider exception to (category, retry_after_seconds).
        Base: unknown — worker applies generic retry/backoff semantics."""
        return None, None
