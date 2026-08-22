"""Canonical events + in-process dispatcher + idempotency store."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import EventError
from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("events")

RISK_LEVELS = {"low", "medium", "high", "critical"}

EVENT_TYPES = {
    "lead.created", "lead.updated", "lead.scored",
    "lead.discovered", "lead.enriched", "lead.duplicate_detected", "lead.rejected",
    "lead.stage_changed",
    "conversation.received", "conversation.updated",
    "sales.conversation_started", "sales.discovery_updated", "sales.qualification_updated",
    "sales.handoff_requested",
    "objection.detected", "offer.recommended",
    "opportunity.created", "opportunity.updated",
    "message.sent", "message.failed",
    "offer.generated", "price.calculated", "negotiation.started",
    "approval.requested", "approval.approved", "approval.rejected",
    "proposal.created", "proposal.sent",
    "deal.won", "deal.lost",
    "project.created", "project.updated",
    "care_plan.created",
    "followup.due", "followup.planned", "followup.cancelled", "followup.sent",
    "content.drafted", "content.review", "content.approved", "content.rejected", "content.published",
    "research.started", "research.completed", "research.failed",
    "job.created", "job.completed", "job.failed",
}


@dataclass
class CanonicalEvent:
    event_id: str
    event_type: str
    timestamp: str
    source: str = "system"
    channel: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None
    risk_level: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.event_id:
            raise EventError("event_id is required")
        if self.event_type not in EVENT_TYPES:
            raise EventError(f"unknown event_type: {self.event_type}")
        if not self.timestamp:
            raise EventError("timestamp is required")
        if self.risk_level is not None and self.risk_level not in RISK_LEVELS:
            raise EventError(f"invalid risk_level: {self.risk_level}")

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["payload"] = json.dumps(self.payload, ensure_ascii=False)
        d["metadata"] = json.dumps(self.metadata, ensure_ascii=False)
        return d


class EventDispatcher:
    """Minimal in-process publish/subscribe dispatcher."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[CanonicalEvent], None]]] = defaultdict(list)
        self.errors: list[dict] = []

    def subscribe(self, event_type: str, handler: Callable[[CanonicalEvent], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: CanonicalEvent) -> None:
        event.validate()
        for handler in self._handlers.get(event.event_type, []):
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 — dispatcher must isolate handler errors
                self.errors.append({"event_type": event.event_type, "error": str(exc)})
                log.error("handler failed for %s: %s", event.event_type, exc)

    def dispatch(self, event: CanonicalEvent) -> None:
        self.publish(event)


class IdempotencyStore:
    """Prevent duplicate execution of external actions via idempotency_key."""

    def __init__(self, db: Database):
        self.db = db

    def check(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT result FROM idempotency_keys WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return row["result"] if row else None

    def store(self, key: str, operation: str, result: str) -> bool:
        """Persist result for key. Returns False if key already exists (duplicate)."""
        existing = self.check(key)
        if existing is not None:
            return False
        self.db.execute(
            "INSERT INTO idempotency_keys (idempotency_key, operation, result, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, operation, result, utcnow()),
        )
        self.db.commit()
        return True
