"""Dashboard RIL API Layer — trusted internal consumer with project-scoped authorization."""

from __future__ import annotations

import logging
from typing import Any

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService

log = logging.getLogger("amancore.requirements.dashboard")


class DashboardRILAPI:
    """Trusted API exposing read/write RIL views with strict project-scoped authorization."""

    def __init__(self, crm: CRMService, requirements_service: RequirementsService | None = None):
        self.crm = crm
        self.ril = requirements_service or RequirementsService(crm)

    def _authorize(self, lead_id: str, auth_user: dict[str, Any] | None) -> None:
        """Validate user authorization for the given lead/project context."""
        if auth_user is None:
            raise PermissionError("UNAUTHORIZED: Missing authentication credentials")

        # Superusers / Admins have full access
        if auth_user.get("role") in ("admin", "superuser", "owner"):
            return

        allowed_leads = set(auth_user.get("allowed_leads") or [])
        allowed_projects = set(auth_user.get("allowed_projects") or [])

        # Check lead access
        if lead_id in allowed_leads:
            return

        # Check project access
        project_scope = self.crm.get_project_scope_for_lead(lead_id)
        project_id = project_scope.get("project_id") if project_scope else None
        if project_id and project_id in allowed_projects:
            return

        log.warning("dashboard.unauthorized_access user=%s lead=%s", auth_user.get("user_id"), lead_id)
        raise PermissionError(f"FORBIDDEN: User {auth_user.get('user_id')} is not authorized for lead {lead_id}")

    # ── Read APIs ─────────────────────────────────────────────────────────────

    def get_requirements(self, lead_id: str, auth_user: dict[str, Any]) -> list[dict[str, Any]]:
        self._authorize(lead_id, auth_user)
        return self.crm.list_requirements_for_lead(lead_id)

    def get_decisions(self, lead_id: str, auth_user: dict[str, Any]) -> list[dict[str, Any]]:
        self._authorize(lead_id, auth_user)
        return self.crm.list_decisions_for_lead(lead_id, status=None)

    def get_conflicts(self, lead_id: str, auth_user: dict[str, Any]) -> list[dict[str, Any]]:
        self._authorize(lead_id, auth_user)
        return self.crm.list_conflicts_for_lead(lead_id, status=None)

    def get_questions(self, lead_id: str, auth_user: dict[str, Any]) -> list[dict[str, Any]]:
        self._authorize(lead_id, auth_user)
        return self.crm.list_open_questions_for_lead(lead_id, status=None)

    def get_coverage(self, lead_id: str, auth_user: dict[str, Any]) -> dict[str, Any]:
        self._authorize(lead_id, auth_user)
        reqs = self.crm.list_requirements_for_lead(lead_id)
        decs = self.crm.list_decisions_for_lead(lead_id, status="active")
        report = self.ril.coverage_analyzer.analyze(
            tier="website",
            requirements=reqs,
            decisions=decs,
        )
        return report.to_dict()

    def get_scope(self, lead_id: str, auth_user: dict[str, Any]) -> dict[str, Any] | None:
        self._authorize(lead_id, auth_user)
        scope = self.crm.get_project_scope_for_lead(lead_id)
        if not scope:
            return None
        latest_version = self.crm.get_latest_scope_version(scope["scope_id"])
        items = self.crm.list_scope_items(latest_version["version_id"]) if latest_version else []
        return {
            "scope": scope,
            "latest_version": latest_version,
            "items": items,
        }

    def get_project_dashboard_view(self, lead_id: str, auth_user: dict[str, Any]) -> dict[str, Any]:
        """Aggregate full project-scoped RIL view model."""
        self._authorize(lead_id, auth_user)
        reqs = self.crm.list_requirements_for_lead(lead_id)
        must_haves = [r for r in reqs if r.get("priority") == "must_have"]
        decs = self.crm.list_decisions_for_lead(lead_id, status="active")
        confs = self.crm.list_conflicts_for_lead(lead_id, status="open")
        qs = self.crm.list_open_questions_for_lead(lead_id, status="open")
        cov = self.ril.coverage_analyzer.analyze(tier="website", requirements=reqs, decisions=decs).to_dict()
        scope_view = self.get_scope(lead_id, auth_user)

        last_msg = None
        try:
            row = self.crm.db.execute(
                "SELECT body FROM channel_messages WHERE direction = 'inbound' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                last_msg = row["body"]
        except Exception:
            pass

        return {
            "lead_id": lead_id,
            "coverage_percentage": cov.get("coverage_score", 0.0),
            "requirements": reqs,
            "must_have_requirements": must_haves,
            "open_questions": qs,
            "active_decisions": decs,
            "conflicts": confs,
            "latest_scope": scope_view,
            "last_source_message": last_msg,
        }

    # ── Mutation APIs (Strict Domain Routing) ────────────────────────────────

    def confirm_requirement(self, lead_id: str, requirement_id: str, auth_user: dict[str, Any]) -> None:
        self._authorize(lead_id, auth_user)
        self.crm.db.execute(
            "UPDATE requirements SET status = 'confirmed', updated_at = datetime('now') WHERE requirement_id = ? AND lead_id = ?",
            (requirement_id, lead_id),
        )
        self.crm.db.commit()

    def reject_requirement(self, lead_id: str, requirement_id: str, reason: str, auth_user: dict[str, Any]) -> None:
        self._authorize(lead_id, auth_user)
        self.crm.db.execute(
            "UPDATE requirements SET status = 'rejected', updated_at = datetime('now') WHERE requirement_id = ? AND lead_id = ?",
            (requirement_id, lead_id),
        )
        self.crm.db.commit()

    def update_decision(
        self,
        lead_id: str,
        topic: str,
        new_value: str,
        rationale: str,
        auth_user: dict[str, Any],
    ) -> str:
        self._authorize(lead_id, auth_user)
        return self.ril.decision_tracker.record_decision(
            lead_id=lead_id,
            topic=topic,
            decision_value=new_value,
            rationale=rationale,
            decided_by=auth_user.get("user_id", "dashboard_user"),
        )

    def resolve_conflict(
        self,
        lead_id: str,
        conflict_id: str,
        resolution: str,
        auth_user: dict[str, Any],
    ) -> None:
        self._authorize(lead_id, auth_user)
        self.crm.resolve_conflict(conflict_id=conflict_id, resolution=resolution)

    def answer_open_question(
        self,
        lead_id: str,
        question_id: str,
        answer: str,
        auth_user: dict[str, Any],
    ) -> None:
        self._authorize(lead_id, auth_user)
        self.crm.update_open_question(question_id=question_id, status="answered")

    def generate_scope(
        self,
        lead_id: str,
        tier: str = "website",
        auth_user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._authorize(lead_id, auth_user)
        scope_version = self.ril.scope_builder.build_or_update_scope(lead_id=lead_id, tier=tier)
        return {
            "status": "generated" if scope_version else "no_requirements",
            "version_number": scope_version.version_number if scope_version else None,
            "total_hours": scope_version.total_estimated_hours if scope_version else 0.0,
        }
