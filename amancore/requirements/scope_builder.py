"""Scope Builder — compiles validated requirements and decisions into an immutable, versioned Scope of Work (SOW)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .models import ScopeItem, ScopeVersion

log = logging.getLogger("amancore.requirements.scope_builder")


class ScopeBuilder:
    """Builds and version-controls formal project scopes from active requirements."""

    def __init__(self, crm):
        self.crm = crm

    def build_or_update_scope(
        self,
        lead_id: str,
        tier: str = "website",
        project_id: str | None = None,
        force_new_version: bool = False,
    ) -> ScopeVersion | None:
        """Compile current requirements into a scope version. Avoids creating duplicate versions if unchanged."""
        if not lead_id:
            return None

        reqs = self.crm.list_requirements_for_lead(lead_id)
        if not reqs:
            return None

        decs = self.crm.list_decisions_for_lead(lead_id, status="active")

        # Get or create project scope container
        scope = self.crm.get_project_scope_for_lead(lead_id)
        if scope is None:
            scope_id = self.crm.create_project_scope(
                lead_id=lead_id,
                project_id=project_id,
                tier=tier,
                summary=f"Project Scope for {tier.replace('_', ' ').title()}",
            )
            version_number = 1
            log.info("scope.created lead=%s scope_id=%s tier=%s", lead_id, scope_id, tier)
        else:
            scope_id = scope["scope_id"]
            latest_v = self.crm.get_latest_scope_version(scope_id)
            if latest_v is not None and not force_new_version:
                existing_items = self.crm.list_scope_items(latest_v["version_id"])
                existing_req_ids = {i.get("requirement_id") for i in existing_items if i.get("requirement_id")}
                current_req_ids = {r.get("requirement_id") for r in reqs if r.get("requirement_id")}

                # If requirements haven't changed, return existing immutable version without incrementing
                if existing_req_ids == current_req_ids and len(existing_items) == len(reqs):
                    log.debug("scope.unchanged lead=%s version=%d", lead_id, latest_v["version_number"])
                    return ScopeVersion(
                        version_id=latest_v["version_id"],
                        scope_id=scope_id,
                        version_number=latest_v["version_number"],
                        items=[
                            ScopeItem(
                                item_id=it["item_id"],
                                version_id=it["version_id"],
                                requirement_id=it.get("requirement_id"),
                                title=it["title"],
                                description=it.get("description"),
                                deliverable=it.get("deliverable"),
                                complexity=it.get("complexity", "standard"),
                                sort_order=it.get("sort_order", 0),
                            )
                            for it in existing_items
                        ],
                        total_estimated_hours=latest_v.get("total_estimated_hours", 0.0) or 0.0,
                        status=latest_v.get("status", "draft"),
                    )

                version_number = latest_v["version_number"] + 1
                # Transition previous draft to superseded
                if latest_v.get("status") == "draft":
                    self.crm.db.execute(
                        "UPDATE scope_versions SET status = 'superseded', updated_at = datetime('now') WHERE version_id = ?",
                        (latest_v["version_id"],),
                    )
                    self.crm.db.commit()
            else:
                version_number = (latest_v["version_number"] + 1) if latest_v else 1

        # Compile Assumptions and Exclusions
        assumptions = [
            f"Language support: {next((d['decision'] for d in decs if d['topic'] == 'languages'), 'English/Arabic as specified')}",
            f"Currency standard: {next((d['decision'] for d in decs if d['topic'] == 'currency'), 'IDR/USD')}",
            "Client provides brand assets and final copy texts prior to development handover",
        ]
        exclusions = [
            "Out-of-scope custom integrations not explicitly listed in deliverables",
            "Third-party API subscription costs (e.g. Meta WhatsApp API, SMS gateways)",
        ]

        total_hours = 0.0
        version_id = self.crm.create_scope_version(
            scope_id=scope_id,
            version_number=version_number,
            status="draft",
            total_estimated_hours=0.0,
            assumptions=json.dumps(assumptions, ensure_ascii=False),
            exclusions=json.dumps(exclusions, ensure_ascii=False),
        )

        # Build Scope Items from Requirements
        scope_items: list[ScopeItem] = []
        for idx, req in enumerate(reqs, start=1):
            hours_map = {"core_module": 16.0, "integration": 12.0, "ui_ux": 8.0, "workflow": 10.0}
            est_hours = hours_map.get(req.get("category"), 8.0)
            total_hours += est_hours

            item_id = self.crm.add_scope_item(
                version_id=version_id,
                requirement_id=req["requirement_id"],
                title=req["title"],
                description=req["description"],
                deliverable=f"Delivered module with automated tests and documentation ({req['category']})",
                complexity="standard" if req.get("priority") == "must_have" else "simple",
                sort_order=idx,
            )
            scope_items.append(
                ScopeItem(
                    item_id=item_id,
                    version_id=version_id,
                    requirement_id=req["requirement_id"],
                    title=req["title"],
                    description=req["description"],
                    sort_order=idx,
                )
            )

        # Update total hours on the version
        self.crm.db.execute(
            "UPDATE scope_versions SET total_estimated_hours = ? WHERE version_id = ?",
            (total_hours, version_id),
        )
        self.crm.db.commit()

        log.info(
            "scope.versioned lead=%s scope_id=%s version=%d items=%d hours=%.1f",
            lead_id, scope_id, version_number, len(scope_items), total_hours,
        )

        return ScopeVersion(
            version_id=version_id,
            scope_id=scope_id,
            version_number=version_number,
            items=scope_items,
            assumptions=assumptions,
            exclusions=exclusions,
            total_estimated_hours=total_hours,
            status="draft",
        )
