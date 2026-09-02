"""Decision entity and history factories."""

from __future__ import annotations

from typing import Any
from amancore.requirements.decisions import DecisionTracker
from tests.fixtures.ids import ids


def decision_factory(
    crm,
    lead_id: str,
    topic: str = "currency",
    decision: str = "USD",
    **overrides,
) -> str:
    """Create and persist a ProjectDecision entity via DecisionTracker."""
    tracker = DecisionTracker(crm)
    rationale = overrides.pop("rationale", f"Agreed decision for {topic}")
    decided_by = overrides.pop("decided_by", "customer")
    project_id = overrides.pop("project_id", None)
    source_msg_id = overrides.pop("source_message_id", ids.next("msg"))

    return tracker.record_decision(
        lead_id=lead_id,
        topic=topic,
        decision_value=decision,
        rationale=rationale,
        source_message_id=source_msg_id,
        project_id=project_id,
        decided_by=decided_by,
    )


def decision_history_factory(
    crm,
    lead_id: str,
    sequence: list[tuple[str, str]],
    project_id: str | None = None,
) -> list[str]:
    """Deterministically record a sequence of decision changes for history audit tests."""
    tracker = DecisionTracker(crm)
    dec_ids: list[str] = []
    for topic, val in sequence:
        d_id = tracker.record_decision(
            lead_id=lead_id,
            topic=topic,
            decision_value=val,
            project_id=project_id,
        )
        dec_ids.append(d_id)
    return dec_ids
