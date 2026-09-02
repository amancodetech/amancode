"""Trusted Channel-to-Project & Identity Resolver with Strict Isolation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from amancore.crm.service import CRMService

log = logging.getLogger("amancore.requirements.resolver")


@dataclass(frozen=True)
class ResolvedContext:
    lead_id: str
    project_id: str | None
    conversation_id: str | None
    is_new_lead: bool = False
    is_ambiguous: bool = False
    status: str = "resolved"  # "resolved", "unresolved", "ambiguous"
    error_message: str | None = None


class ChannelProjectResolver:
    """Resolves transport-level identities into canonical Lead and Project context with security boundaries."""

    def __init__(self, crm: CRMService):
        self.crm = crm

    def resolve_context(
        self,
        channel: str,
        sender_id: str,
        auto_create_lead: bool = True,
        sender_name: str | None = None,
        project_hint: str | None = None,
    ) -> ResolvedContext | None:
        """Resolve trusted lead and project context from verified channel identity."""
        clean_channel = channel.lower().strip()
        clean_sender = str(sender_id).strip()

        if not clean_channel or not clean_sender:
            log.warning("resolve.failed reason=missing_identity channel=%s sender=%s", clean_channel, clean_sender)
            return None

        # 1. Look up existing identity
        lead = self.crm.find_lead_by_identity(channel=clean_channel, external_user_id=clean_sender)
        is_new = False

        if lead is None and clean_channel == "whatsapp":
            lead = self.crm.find_lead_by_whatsapp(clean_sender)

        # 2. Auto-create lead if not found and allowed
        if lead is None:
            if not auto_create_lead:
                log.info("resolve.unresolved_identity channel=%s sender=%s", clean_channel, clean_sender)
                return ResolvedContext(
                    lead_id="",
                    project_id=None,
                    conversation_id=None,
                    status="unresolved",
                    error_message="UNKNOWN_IDENTITY: Unrecognized customer identity",
                )

            lead_id = self.crm.create_lead(
                name=sender_name or f"User {clean_sender[:6]}",
                preferred_channel=clean_channel,
                contact_whatsapp=clean_sender if clean_channel == "whatsapp" else None,
            )
            self.crm.add_lead_identity(lead_id=lead_id, channel=clean_channel, external_user_id=clean_sender)
            lead = self.crm.get_lead(lead_id)
            is_new = True

        lead_id = lead["lead_id"]

        # 3. Resolve active project context for this lead
        project_id = None
        scopes = self.crm.db.execute(
            "SELECT DISTINCT project_id FROM project_scopes WHERE lead_id = ? AND project_id IS NOT NULL",
            (lead_id,),
        ).fetchall()

        if len(scopes) > 1 and not project_hint:
            log.warning("resolve.ambiguous_projects lead=%s count=%d", lead_id, len(scopes))
            return ResolvedContext(
                lead_id=lead_id,
                project_id=None,
                conversation_id=None,
                is_ambiguous=True,
                status="ambiguous",
                error_message="AMBIGUOUS_PROJECT: Multiple active projects found without explicit project reference",
            )
        elif len(scopes) == 1:
            project_id = scopes[0]["project_id"]
        elif project_hint:
            matching = [s["project_id"] for s in scopes if s["project_id"] == project_hint]
            if matching:
                project_id = matching[0]

        # 4. Resolve active conversation
        conv = self.crm.get_conversation_for_lead(lead_id)
        conversation_id = conv.get("conversation_id") if conv else None

        return ResolvedContext(
            lead_id=lead_id,
            project_id=project_id,
            conversation_id=conversation_id,
            is_new_lead=is_new,
            status="resolved",
        )

    def verify_project_isolation(
        self,
        lead_id: str,
        conversation_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Verify strict relational boundaries between lead, conversation, and project."""
        if not lead_id:
            return False

        # If conversation specified, ensure it belongs to the lead
        if conversation_id:
            conv = self.crm.db.execute(
                "SELECT conversation_id, lead_id FROM conversations WHERE conversation_id = ? LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if conv and conv["lead_id"] != lead_id:
                log.error("isolation.violation conversation=%s does not belong to lead=%s", conversation_id, lead_id)
                return False

        # If project specified, ensure project belongs to lead's scope
        if project_id:
            scope = self.crm.get_project_scope_for_lead(lead_id)
            if scope and scope.get("project_id") and scope["project_id"] != project_id:
                log.error("isolation.violation project=%s does not match lead scope=%s", project_id, scope["project_id"])
                return False

        return True
