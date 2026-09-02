"""Requirement entity factory."""

from __future__ import annotations

from typing import Any
from tests.fixtures.ids import ids


def requirement_factory(crm, lead_id: str, **overrides) -> str:
    """Create and persist a valid Requirement entity with deterministic defaults."""
    req_id = overrides.pop("requirement_id", ids.next("req"))
    category = overrides.pop("category", "core_module")
    subcategory = overrides.pop("subcategory", "ecommerce")
    title = overrides.pop("title", "Online Store & Product Catalog")
    description = overrides.pop("description", "Customer requested online store with shopping cart")
    priority = overrides.pop("priority", "must_have")
    certainty = overrides.pop("certainty", "explicit")
    confidence = overrides.pop("confidence", 1.0)
    status = overrides.pop("status", "captured")

    return crm.create_requirement(
        lead_id=lead_id,
        requirement_id=req_id,
        category=category,
        subcategory=subcategory,
        title=title,
        description=description,
        priority=priority,
        certainty=certainty,
        confidence=confidence,
        status=status,
        **overrides,
    )
