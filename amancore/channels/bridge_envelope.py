"""BridgeEnvelope → BridgeNormalizer → existing CanonicalEvent.

Owner spec §11/§12/§16: the Node bridge emits a NEUTRAL envelope; this module
is the single conversion point into the EXISTING CanonicalEvent model so the
bridge reuses the same intake pipeline as the Graph webhooks.

IDENTITY PARITY (§16 — mandatory): idempotency keys and external_user_id
values MUST be byte-identical to the Graph adapters for the same platform
user/message:
    whatsapp  idem `wa:{wamid}`        user = E164 digits
    facebook  idem `fb:{mid}`          user = Messenger PSID
    instagram idem `ig:{mid}`          user = IG scoped id
"""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..log import get_logger
from ..services.events import CanonicalEvent

log = get_logger("channels.bridge_envelope")

# channel → idempotency prefix — MUST match the Graph adapters exactly
IDEMPOTENCY_PREFIX = {"whatsapp": "wa", "facebook": "fb",
                      "instagram": "ig", "telegram": "tg"}

# event_type values the bridge may push
ENVELOPE_EVENT_TYPES = ("message.received", "message.reaction", "message.status")

MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")


class EnvelopeError(ValueError):
    """Malformed bridge envelope — NOT retryable (the payload is bad)."""

    def __init__(self, message: str, *, error_code: str = "INVALID_ENVELOPE"):
        super().__init__(message)
        self.error_code = error_code


def normalize_envelope(data) -> CanonicalEvent:
    """Convert one bridge envelope into the existing CanonicalEvent model.

    Raises EnvelopeError for anything the pipeline must not touch — the
    /bridge/inbound endpoint maps that to a non-retryable ACK.
    """
    if not isinstance(data, dict):
        raise EnvelopeError("envelope must be a JSON object")
    channel = str(data.get("channel") or "")
    if channel not in IDEMPOTENCY_PREFIX:
        raise EnvelopeError(f"unknown bridge channel: {channel!r}",
                            error_code="UNKNOWN_CHANNEL")
    event_type = str(data.get("event_type") or "")
    if event_type not in ENVELOPE_EVENT_TYPES:
        raise EnvelopeError(f"unsupported event_type: {event_type!r}")

    sender = data.get("sender") or {}
    external_user_id = str(sender.get("external_id") or "")
    if not external_user_id:
        raise EnvelopeError("missing sender.external_id")

    external_message_id = str(data.get("external_message_id") or "")
    if not external_message_id:
        # statuses/reactions always reference a platform message id
        raise EnvelopeError("missing external_message_id")

    prefix = IDEMPOTENCY_PREFIX[channel]
    idem = f"{prefix}:{external_message_id}"
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("provider_message_id", external_message_id)
    if data.get("account_id"):
        metadata["account_id"] = str(data["account_id"])

    if event_type == "message.received":
        return _received(channel, data, sender, external_user_id,
                         external_message_id, idem, metadata)
    if event_type == "message.reaction":
        return _reaction(channel, data, external_user_id,
                         external_message_id, idem, metadata)
    return _status(channel, data, external_user_id,
                   external_message_id, idem, metadata)


def _received(channel, data, sender, external_user_id, external_message_id,
              idem, metadata) -> CanonicalEvent:
    message = data.get("message") or {}
    if not isinstance(message, dict):
        raise EnvelopeError("message must be an object")
    msg_type = str(message.get("type") or "text")
    text = str(message.get("text") or "")
    if msg_type in MEDIA_TYPES:
        media = message.get("media")
        if not isinstance(media, dict) or not (
                media.get("media_id") or media.get("base64")):
            # media envelope without payload bytes/reference is unusable
            raise EnvelopeError(f"{msg_type} message missing media payload")
        text = str(message.get("caption") or text)
    elif msg_type != "text":
        # unsupported message kinds are recorded as opaque, never crash intake
        msg_type = "unsupported"
    reply_to = (message.get("reply_to") or data.get("reply_to_message_id") or None)
    media_payload = message.get("media") if msg_type in MEDIA_TYPES else None
    return CanonicalEvent(
        event_id=str(data.get("event_id") or new_id()),
        event_type="message.received",
        timestamp=str(data.get("timestamp") or utcnow()),
        source=channel,
        channel=channel,
        actor_type="external",
        actor_id=external_user_id,
        idempotency_key=idem,
        risk_level="low",
        payload={
            "external_user_id": external_user_id,
            "name": str(sender.get("name") or ""),
            "message_type": msg_type,
            "text": text,
            "timestamp": data.get("timestamp"),
            "reply_to_external_message_id": str(reply_to) if reply_to else None,
            "media": media_payload,
        },
        metadata=metadata,
    )


def _reaction(channel, data, external_user_id, external_message_id,
              idem, metadata) -> CanonicalEvent:
    emoji = str((data.get("message") or {}).get("emoji")
                or data.get("emoji") or "")
    target = str(data.get("target_message_id") or "")
    if not target:
        raise EnvelopeError("reaction envelope missing target_message_id")
    return CanonicalEvent(
        event_id=str(data.get("event_id") or new_id()),
        event_type="message.reaction",
        timestamp=str(data.get("timestamp") or utcnow()),
        source=channel,
        channel=channel,
        actor_type="external",
        actor_id=external_user_id,
        # reactions key on the platform's reaction-id; fall back to a
        # derived key so a retried push never double-applies
        idempotency_key=idem if data.get("external_message_id")
        else f"{IDEMPOTENCY_PREFIX[channel]}-react:{external_message_id}",
        risk_level="low",
        payload={
            "external_user_id": external_user_id,
            "target_external_message_id": target,
            "emoji": emoji,
        },
        metadata=metadata,
    )


def _status(channel, data, external_user_id, external_message_id,
            idem, metadata) -> CanonicalEvent:
    status = str((data.get("message") or {}).get("status")
                 or data.get("status") or "")
    if status not in ("sent", "delivered", "read", "failed"):
        raise EnvelopeError(f"unsupported message status: {status!r}")
    return CanonicalEvent(
        event_id=str(data.get("event_id") or new_id()),
        event_type=f"message.{status}",
        timestamp=str(data.get("timestamp") or utcnow()),
        source=channel,
        channel=channel,
        actor_type="external",
        actor_id=external_user_id,
        idempotency_key=f"{IDEMPOTENCY_PREFIX[channel]}-status:{external_message_id}:{status}",
        risk_level="low",
        payload={
            "status": status,
            "external_message_id": external_message_id,
            "recipient_external_user_id": external_user_id,
        },
        metadata=metadata,
    )
