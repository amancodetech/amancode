"""Agent base — shared context, audit, and event emission.

Agents never: send external messages, publish content, write Business Brain,
or access SQLite directly. They act only through services passed to them.
"""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..log import get_logger
from ..services.events import CanonicalEvent, EventDispatcher


class Agent:
    def __init__(
        self,
        name: str,
        brain_store,
        crm=None,
        router=None,
        audit=None,
        dispatcher: EventDispatcher | None = None,
    ):
        self.name = name
        self.brain_store = brain_store
        self.crm = crm
        self.router = router
        self.audit = audit
        self.dispatcher = dispatcher
        self.log = get_logger(f"agents.{name}")

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def _audit(self, action: str, resource: str, **fields) -> None:
        if self.audit is not None:
            self.audit.record(agent=self.name, action=action, resource=resource, **fields)

    def _emit(
        self,
        event_type: str,
        payload: dict | None = None,
        correlation_id: str | None = None,
        risk_level: str | None = None,
    ) -> CanonicalEvent | None:
        if self.dispatcher is None:
            return None
        event = CanonicalEvent(
            event_id=new_id(),
            event_type=event_type,
            timestamp=utcnow(),
            source=self.name,
            actor_type="agent",
            actor_id=self.name,
            correlation_id=correlation_id,
            risk_level=risk_level,
            payload=payload or {},
        )
        self.dispatcher.publish(event)
        return event
