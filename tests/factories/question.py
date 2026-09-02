"""Open question entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def question_factory(
    crm,
    lead_id: str,
    question: str = "Which payment gateways do you plan to support?",
    **overrides,
) -> str:
    """Create and persist an OpenQuestion entity."""
    question_id = overrides.pop("question_id", ids.next("question"))
    priority = overrides.pop("priority", 50)
    category = overrides.pop("category", "integration")
    reason = overrides.pop("reason", "Clarify payment integration scope")
    requirement_id = overrides.pop("requirement_id", None)
    status = overrides.pop("status", "open")
    project_id = overrides.pop("project_id", None)

    return crm.create_open_question(
        question_id=question_id,
        lead_id=lead_id,
        project_id=project_id,
        requirement_id=requirement_id,
        question=question,
        reason=reason,
        priority=priority,
        category=category,
        status=status,
    )
