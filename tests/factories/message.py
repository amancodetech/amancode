"""Message entity factory supporting WhatsApp, Telegram, Messenger, and Instagram."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def message_factory(
    crm,
    lead_id: str,
    body: str = "Test requirement message",
    channel: str = "whatsapp",
    direction: str = "in",
    **overrides,
) -> dict[str, Any]:
    """Create and persist a channel message in the database."""
    ext_msg_id = overrides.pop("external_message_id", ids.next("msg"))
    ext_user_id = overrides.pop("external_user_id", f"user_{lead_id}")

    fields = {
        "channel": channel,
        "direction": direction,
        "external_user_id": ext_user_id,
        "lead_id": lead_id,
        "external_message_id": ext_msg_id,
        "body": body,
        "status": "delivered",
        "created_at": "2026-09-02T12:00:00+00:00",
        "hidden": 0,
    }
    fields.update(overrides)

    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    crm.db.execute(
        f"INSERT INTO channel_messages ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    crm.db.commit()
    return fields
