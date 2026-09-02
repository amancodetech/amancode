"""Conversation entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def conversation_factory(crm, lead_id: str, **overrides) -> str:
    """Create and persist a valid Conversation entity."""
    conversation_id = overrides.pop("conversation_id", ids.next("conversation"))
    channel = overrides.pop("channel", "whatsapp")
    language = overrides.pop("language", "ar")

    fields = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel": channel,
        "language": language,
        "facts": "{}",
        "preferences": "{}",
        "requirements": "{}",
        "created_at": "2026-09-02T12:00:00+00:00",
        "updated_at": "2026-09-02T12:00:00+00:00",
    }
    fields.update(overrides)

    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    crm.db.execute(
        f"INSERT INTO conversations ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    crm.db.commit()
    return conversation_id
