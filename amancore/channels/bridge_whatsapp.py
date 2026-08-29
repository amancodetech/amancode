"""Bridge WhatsApp provider — same surface as the Graph provider, local
meta-bridge behind it (Baileys lives ONLY inside the bridge; owner spec §17).

Identity/retry/state semantics are inherited from the existing pipeline:
  - send      → transport (delivery_unknown honored by the OutboxWorker)
  - send_raw  → reactions / read receipts (official-shape bodies mapped)
  - upload/download media → bridge media endpoints (base64 transport)
  - production gate: block_unless_production_enabled — identical to Graph
"""

from __future__ import annotations

from ..log import get_logger
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from ..ids import new_id, utcnow
from .bridge_transport import BridgeError, BridgeTransport, bridge_health_probe
from .canonical import ChannelCapabilities
from .contract import ChannelAdapter
from .wa_errors import normalize_e164_digits

log = get_logger("channels.bridge_whatsapp")

MAX_TEXT = 4096


class BridgeWhatsAppProvider:
    """WhatsApp transport over the local meta-bridge."""

    def __init__(self, config: dict):
        self.config = config
        self.transport = BridgeTransport(config)

    # ---- messages -------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        block_unless_production_enabled(self.config)
        message: dict = {"type": message_type, "recipient": recipient}
        if message_type == "text":
            body = payload if isinstance(payload, str) \
                else (payload or {}).get("body", "")
            message["text"] = str(body or "")[:MAX_TEXT]
            reply_to = (payload or {}).get("_reply_to") \
                if isinstance(payload, dict) else None
            if reply_to:
                message["reply_to"] = str(reply_to)
        elif message_type in ("image", "audio", "video", "document", "sticker"):
            if not isinstance(payload, dict):
                raise BridgeError("invalid_request",
                                  f"media payload must be a dict: {message_type}")
            if payload.get("data_base64"):
                message["media"] = {
                    "base64": payload["data_base64"],
                    "mime": payload.get("mime", "application/octet-stream"),
                    "filename": payload.get("filename"),
                    "caption": payload.get("caption"),
                }
            elif payload.get("id"):
                message["media"] = {"media_id": str(payload["id"]),
                                    "caption": payload.get("caption"),
                                    "filename": payload.get("filename")}
            else:
                raise BridgeError("invalid_request",
                                  "media payload requires data_base64 or id")
        else:
            raise BridgeError("invalid_request",
                              f"unsupported message type: {message_type}")
        result = self.transport.send_message("whatsapp", message)
        return {"provider_message_id": str(result.get("external_message_id") or ""),
                "status": str(result.get("status") or "sent"),
                "would_send": bool(result.get("would_send"))}

    def send_raw(self, body: dict) -> dict:
        """Official-shape payloads: reactions (type=reaction) and read
        receipts (status=read) map onto dedicated bridge endpoints."""
        block_unless_production_enabled(self.config)
        if not isinstance(body, dict):
            raise BridgeError("invalid_request", "send_raw body must be an object")
        if body.get("type") == "reaction":
            reaction = body.get("reaction") or {}
            result = self.transport.react("whatsapp",
                                          str(reaction.get("message_id") or ""),
                                          str(reaction.get("emoji") or ""))
            return {"delivered": True, "would_send": bool(result.get("would_send"))}
        if body.get("status") == "read":
            mid = str(body.get("message_id") or "")
            result = self.transport.mark_read("whatsapp", [mid] if mid else [])
            return {"delivered": True, "would_send": bool(result.get("would_send"))}
        raise BridgeError("invalid_request",
                          f"unsupported send_raw body: {str(body)[:120]}")

    # ---- media ----------------------------------------------------------
    def upload_media(self, data: bytes, mime: str, filename: str = "file") -> str:
        block_unless_production_enabled(self.config)
        return self.transport.upload_media(data, mime, filename,
                                           channel="whatsapp")

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        return self.transport.download_media(str(media_id), channel="whatsapp")

    # ---- ops ------------------------------------------------------------
    def health(self) -> dict:
        return self.transport.health()


class BridgeWhatsAppAdapter(ChannelAdapter):
    """WhatsApp via the local bridge. Webhook intake is REPLACED by
    /bridge/inbound pushes (receive_webhook → []); the Meta GET handshake is
    not part of this transport."""

    channel = "whatsapp"

    def __init__(self, config: dict, provider=None):
        self.config = dict(config or {})
        self.provider = provider or BridgeWhatsAppProvider(self.config)

    # ---- contract surface ----------------------------------------------
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            text=True, image=True, audio=True, video=True, document=True,
            sticker=True, template=False, reaction=True, read_receipt=True,
            reply_context=True)

    def normalize_recipient(self, raw) -> str:
        """IDENTITY PARITY (owner spec §16): E164 digits, same as Graph."""
        return normalize_e164_digits(str(raw or ""))

    # ---- webhook surface (unused in bridge mode) ------------------------
    def verify_webhook(self, mode: str = "", token: str = "",
                       challenge: str = "") -> dict:
        return {"verified": False,
                "error": "bridge mode ingests via /bridge/inbound "
                         "(X-Bridge-Token), no Meta handshake"}

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        return False  # fail-closed: never accept Meta-signed posts in bridge mode

    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        return []

    # ---- send -----------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        return self.provider.send(recipient, message_type, payload)

    def react(self, recipient: str, message_id: str, emoji: str) -> dict:
        return self.provider.send_raw(
            {"messaging_product": "whatsapp", "type": "reaction",
             "reaction": {"message_id": message_id, "emoji": emoji}})

    def mark_read(self, message_id: str) -> dict:
        return self.provider.send_raw({"status": "read", "message_id": message_id})

    # ---- errors / ops ---------------------------------------------------
    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        if isinstance(exc, BridgeError):
            return exc.category, exc.retry_after_seconds
        return None, None

    def health_probe(self) -> str:
        state = bridge_health_probe(self.config)
        if state["process"] != "UP":
            raise RuntimeError(f"bridge DOWN: {state['detail']}")
        shadow = " shadow=ON" if self.config.get("bridge", {}).get("shadow") else ""
        return (f"bridge UP transport={self.config.get('bridge', {}).get('transport', '?')}"
                f"{shadow} session={state['session']}")
