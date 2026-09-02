"""Lead entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def lead_factory(crm, **overrides) -> str:
    """Create and persist a valid Lead entity in the database with deterministic defaults."""
    lead_id = overrides.pop("lead_id", ids.next("lead"))
    name = overrides.pop("name", f"Test Customer {lead_id}")
    phone = overrides.pop("contact_whatsapp", "62810000000")
    channel = overrides.pop("preferred_channel", "whatsapp")

    # Insert directly or via CRM
    fields = {
        "lead_id": lead_id,
        "name": name,
        "contact_whatsapp": phone,
        "preferred_channel": channel,
        "status": "new",
        "lead_stage": "nurture",
        "lead_score": 0,
        "created_at": "2026-09-02T12:00:00+00:00",
        "updated_at": "2026-09-02T12:00:00+00:00",
    }
    fields.update(overrides)

    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    crm.db.execute(
        f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    crm.db.commit()
    return lead_id
