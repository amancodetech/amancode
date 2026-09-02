"""Project scope, version, and item factories."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def scope_factory(crm, lead_id: str, tier: str = "website", **overrides) -> str:
    """Create and persist a ProjectScope entity."""
    scope_id = overrides.pop("scope_id", ids.next("scope"))
    project_id = overrides.pop("project_id", None)
    current_v = overrides.pop("current_version_number", 1)

    return crm.create_project_scope(
        scope_id=scope_id,
        lead_id=lead_id,
        project_id=project_id,
        tier=tier,
        current_version_number=current_v,
    )


def scope_version_factory(
    crm,
    scope_id: str,
    version_number: int = 1,
    **overrides,
) -> str:
    """Create and persist a ScopeVersion entity."""
    version_id = overrides.pop("version_id", ids.next("scope_ver"))
    assumptions = overrides.pop("assumptions", "[]")
    exclusions = overrides.pop("exclusions", "[]")
    hours = overrides.pop("total_estimated_hours", 16.0)
    status = overrides.pop("status", "draft")

    return crm.create_scope_version(
        version_id=version_id,
        scope_id=scope_id,
        version_number=version_number,
        assumptions=assumptions,
        exclusions=exclusions,
        total_estimated_hours=hours,
        status=status,
    )


def scope_item_factory(
    crm,
    version_id: str,
    title: str = "E-Commerce System Setup",
    requirement_id: str | None = None,
    **overrides,
) -> str:
    """Create and persist a ScopeItem entity."""
    item_id = overrides.pop("item_id", ids.next("scope_item"))
    desc = overrides.pop("description", "Deliverable item specification")
    deliverable = overrides.pop("deliverable", "Working component")
    complexity = overrides.pop("complexity", "standard")
    is_included = overrides.pop("is_included", True)
    sort_order = overrides.pop("sort_order", 0)

    return crm.add_scope_item(
        item_id=item_id,
        version_id=version_id,
        requirement_id=requirement_id,
        title=title,
        description=desc,
        deliverable=deliverable,
        complexity=complexity,
        is_included=is_included,
        sort_order=sort_order,
    )


def scope_snapshot(crm, version_id: str) -> dict[str, Any]:
    """Fetch complete immutable snapshot of a scope version and its items."""
    ver_row = crm.db.execute(
        "SELECT * FROM scope_versions WHERE version_id = ?",
        (version_id,),
    ).fetchone()
    if not ver_row:
        return {}
    items = crm.list_scope_items(version_id)
    return {
        "version": dict(ver_row),
        "items": items,
    }
