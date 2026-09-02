"""Requirement conflict entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def conflict_factory(
    crm,
    lead_id: str,
    requirement_a_id: str,
    requirement_b_id: str,
    conflict_type: str = "mutual_exclusion",
    explanation: str = "Conflict between requirements A and B",
    **overrides,
) -> str:
    """Create and persist a RequirementConflict entity."""
    conflict_id = overrides.pop("conflict_id", ids.next("conflict"))
    status = overrides.pop("status", "open")
    project_id = overrides.pop("project_id", None)
    resolution = overrides.pop("resolution", None)

    return crm.create_conflict(
        conflict_id=conflict_id,
        lead_id=lead_id,
        project_id=project_id,
        requirement_a_id=requirement_a_id,
        requirement_b_id=requirement_b_id,
        conflict_type=conflict_type,
        explanation=explanation,
        status=status,
        resolution=resolution,
    )
