"""Canonical transport model — the only message shape the Core understands.

Provider-specific identifiers (wa_id, wamid, telegram chat ids, ...) exist
ONLY inside adapters. The core speaks exclusively in external_* generics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..services.events import CanonicalEvent


@dataclass(frozen=True)
class InboundMessage:
    """One normalized customer message from any channel."""

    channel: str
    external_message_id: str
    external_user_id: str
    text: str = ""
    name: str = ""
    message_type: str = "text"
    timestamp: str | None = None
    reply_to_external_message_id: str | None = None
    external_conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    media: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_event(cls, evt: CanonicalEvent) -> "InboundMessage":
        p = evt.payload or {}
        return cls(
            channel=evt.channel or evt.source or "unknown",
            external_message_id=str(evt.metadata.get("provider_message_id")
                                     or p.get("external_message_id") or ""),
            external_user_id=str(p.get("external_user_id") or ""),
            text=str(p.get("text") or ""),
            name=str(p.get("name") or ""),
            message_type=str(p.get("message_type") or "text"),
            timestamp=p.get("timestamp"),
            reply_to_external_message_id=p.get("reply_to_external_message_id") or None,
            metadata=dict(evt.metadata or {}),
            media=dict(p.get("media") or {}),
        )


@dataclass(frozen=True)
class ChannelCapabilities:
    """What a channel can actually carry — checked BEFORE any provider call."""

    text: bool = True
    image: bool = False
    audio: bool = False
    video: bool = False
    document: bool = False
    sticker: bool = False
    template: bool = False
    reaction: bool = False
    read_receipt: bool = False
    reply_context: bool = False


TEXT_ONLY = ChannelCapabilities()
