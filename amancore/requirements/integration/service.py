"""RIL Integration Service — canonical gateway, deduplication, event emission & error handling."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from .models import (
    CanonicalInboundMessage,
    CanonicalRILResponse,
    RILErrorCategory,
    RILEvent,
)

log = logging.getLogger("amancore.requirements.integration")


class RILIntegrationService:
    """Canonical integration facade that orchestrates RIL ingestion from all channels."""

    def __init__(self, crm: CRMService, requirements_service: RequirementsService | None = None):
        self.crm = crm
        self.ril = requirements_service or RequirementsService(crm)
        self.events_log: list[RILEvent] = []

    def ingest_canonical_message(self, msg: CanonicalInboundMessage) -> CanonicalRILResponse:
        """Process canonical inbound message through the 17-step pipeline."""
        start_time = time.perf_counter()

        msg_id = msg.canonical_message_id
        text = msg.canonical_content

        # Step 1 & 2: Inbound received & validated
        self._record_event(
            RILEvent(
                event_name="inbound.received",
                lead_id=msg.lead_id or "unknown",
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                message_id=msg_id,
                payload={"channel": msg.channel, "provider": msg.provider},
            )
        )

        if not msg.lead_id or not text:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return CanonicalRILResponse(
                lead_id=msg.lead_id or "",
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                status="error",
                error="INVALID_REQUEST: missing lead_id or message text",
                error_category=RILErrorCategory.INVALID_REQUEST,
                processing_duration_ms=duration_ms,
            )

        # Step 7: Check Idempotency (provider + channel + provider_message_id)
        idempotency_key = f"ril_{msg.provider}_{msg.channel}_{msg_id}"
        existing = self._get_idempotent_result(idempotency_key)
        if existing is not None:
            log.info("idempotency.duplicate channel=%s msg_id=%s", msg.channel, msg_id)
            self._record_event(
                RILEvent(
                    event_name="idempotency.duplicate",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={"idempotency_key": idempotency_key},
                )
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            existing.processing_duration_ms = duration_ms
            return existing

        # Step 8: Persist canonical inbound message log
        try:
            self.crm.db.execute(
                """
                INSERT OR IGNORE INTO channel_messages (channel, external_message_id, external_user_id, direction, body, created_at)
                VALUES (?, ?, ?, 'inbound', ?, datetime('now'))
                """,
                (msg.channel, msg_id, msg.canonical_sender_id, text),
            )
            self.crm.db.commit()
        except Exception:
            pass

        # Step 9-14: Invoke RequirementsService (Extract, Decisions, Conflicts, Coverage, Questions, Scope)
        self._record_event(
            RILEvent(
                event_name="ril.started",
                lead_id=msg.lead_id,
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                message_id=msg_id,
            )
        )

        try:
            ril_dict = self.ril.process_message(
                lead_id=msg.lead_id,
                message=text,
                conversation_id=msg.conversation_id,
                source_message_id=msg_id,
            )

            # Generate fine-grained domain events
            events = self._generate_events(msg, ril_dict)
            for evt in events:
                self._record_event(evt)

            self._record_event(
                RILEvent(
                    event_name="ril.completed",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={
                        "requirements_count": ril_dict.get("total_requirements_count", 0),
                        "coverage": ril_dict.get("coverage_score", 0.0),
                    },
                )
            )

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            response = CanonicalRILResponse(
                lead_id=msg.lead_id,
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                requirements_summary={
                    "total": ril_dict.get("total_requirements_count", 0),
                    "new": ril_dict.get("new_requirements_count", 0),
                },
                new_requirements_count=ril_dict.get("new_requirements_count", 0),
                total_requirements_count=ril_dict.get("total_requirements_count", 0),
                active_decisions=ril_dict.get("active_decisions", {}),
                conflicts_count=ril_dict.get("conflicts_count", 0),
                coverage_score=ril_dict.get("coverage_score", 0.0),
                covered_domains=ril_dict.get("covered_domains", []),
                missing_domains=ril_dict.get("missing_domains", []),
                critical_gaps=ril_dict.get("critical_gaps", []),
                is_ready_for_proposal=ril_dict.get("is_ready_for_proposal", False),
                next_question=ril_dict.get("next_question"),
                scope_version_number=ril_dict.get("scope_version_number"),
                events=[e.__dict__ for e in events],
                processing_duration_ms=duration_ms,
                status="success",
            )

            self._record_event(
                RILEvent(
                    event_name="response.created",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                )
            )

            # Save idempotent result
            self._save_idempotent_result(idempotency_key, response)
            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            log.error("ril.failed channel=%s lead=%s err=%s", msg.channel, msg.lead_id, exc)

            fail_evt = RILEvent(
                event_name="ril.failed",
                lead_id=msg.lead_id,
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                message_id=msg_id,
                payload={"error": str(exc), "channel": msg.channel},
            )
            self._record_event(fail_evt)

            return CanonicalRILResponse(
                lead_id=msg.lead_id,
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                status="error",
                error=str(exc),
                error_category=RILErrorCategory.RIL_FAILURE,
                events=[fail_evt.__dict__],
                processing_duration_ms=duration_ms,
            )

    def _generate_events(self, msg: CanonicalInboundMessage, res: dict[str, Any]) -> list[RILEvent]:
        evts: list[RILEvent] = []
        msg_id = msg.canonical_message_id

        if res.get("new_requirements_count", 0) > 0:
            evts.append(
                RILEvent(
                    event_name="requirement.extracted",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={"new_count": res["new_requirements_count"]},
                )
            )

        if res.get("active_decisions"):
            evts.append(
                RILEvent(
                    event_name="decision.created",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={"decisions": res["active_decisions"]},
                )
            )

        if res.get("conflicts_count", 0) > 0:
            evts.append(
                RILEvent(
                    event_name="conflict.detected",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={"conflicts_count": res["conflicts_count"]},
                )
            )

        if res.get("next_question"):
            evts.append(
                RILEvent(
                    event_name="question.created",
                    lead_id=msg.lead_id,
                    project_id=msg.project_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg_id,
                    payload={"question": res["next_question"]},
                )
            )

        evts.append(
            RILEvent(
                event_name="coverage.updated",
                lead_id=msg.lead_id,
                project_id=msg.project_id,
                conversation_id=msg.conversation_id,
                message_id=msg_id,
                payload={"coverage_score": res.get("coverage_score", 0.0)},
            )
        )

        return evts

    def _record_event(self, evt: RILEvent) -> None:
        self.events_log.append(evt)
        try:
            self.crm.db.execute(
                """
                INSERT INTO events (event_id, event_type, lead_id, payload, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (evt.event_id, evt.event_name, evt.lead_id, json.dumps(evt.payload)),
            )
            self.crm.db.commit()
        except Exception:
            pass

    def _get_idempotent_result(self, key: str) -> CanonicalRILResponse | None:
        try:
            row = self.crm.db.execute(
                "SELECT result FROM idempotency_keys WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row and row[0]:
                data = json.loads(row[0])
                return CanonicalRILResponse(**data)
        except Exception:
            pass
        return None

    def _save_idempotent_result(self, key: str, res: CanonicalRILResponse) -> None:
        try:
            data = {
                "lead_id": res.lead_id,
                "project_id": res.project_id,
                "conversation_id": res.conversation_id,
                "requirements_summary": res.requirements_summary,
                "new_requirements_count": res.new_requirements_count,
                "total_requirements_count": res.total_requirements_count,
                "active_decisions": res.active_decisions,
                "conflicts_count": res.conflicts_count,
                "coverage_score": res.coverage_score,
                "covered_domains": res.covered_domains,
                "missing_domains": res.missing_domains,
                "critical_gaps": res.critical_gaps,
                "is_ready_for_proposal": res.is_ready_for_proposal,
                "next_question": res.next_question,
                "scope_version_number": res.scope_version_number,
                "events": res.events,
                "status": res.status,
            }
            self.crm.db.execute(
                """
                INSERT OR REPLACE INTO idempotency_keys (idempotency_key, operation, result, created_at)
                VALUES (?, 'ril_ingest', ?, datetime('now'))
                """,
                (key, json.dumps(data)),
            )
            self.crm.db.commit()
        except Exception:
            pass
