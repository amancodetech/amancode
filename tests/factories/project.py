"""Project entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def project_factory(crm, **overrides) -> str:
    """Create and persist a valid Project entity in the database with deterministic defaults."""
    project_id = overrides.pop("project_id", ids.next("project"))
    service = overrides.pop("service", "Website System")
    status = overrides.pop("status", "scoping")

    fields = {
        "project_id": project_id,
        "service": service,
        "status": status,
        "hours_logged": 0.0,
        "created_at": "2026-09-02T12:00:00+00:00",
        "updated_at": "2026-09-02T12:00:00+00:00",
    }
    fields.update(overrides)

    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    crm.db.execute(
        f"INSERT INTO projects ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    crm.db.commit()
    return project_id
