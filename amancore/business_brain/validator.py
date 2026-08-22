"""Business Brain content validator (deterministic, no LLM)."""

from __future__ import annotations

from typing import Any

from .schema import (
    OFFER_TIERS,
    REQUIRED_SECTIONS,
    SERVICE_TYPES,
    SUPPORTED_MARKETS,
)


def validate_brain(data: Any) -> list[str]:
    """Return a list of validation errors (empty == valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["business brain must be a mapping"]

    for section in REQUIRED_SECTIONS:
        if section not in data:
            errors.append(f"missing required section: {section}")

    # pricing_policy
    pp = data.get("pricing_policy")
    if isinstance(pp, dict):
        if not isinstance(pp.get("shadow_rate"), (int, float)) or pp.get("shadow_rate", 0) <= 0:
            errors.append("pricing_policy.shadow_rate must be a positive number")
        for key in ("markup_by_service", "minimum_approved_multiplier"):
            if not isinstance(pp.get(key), dict):
                errors.append(f"pricing_policy.{key} must be a mapping")
        mm = pp.get("market_multiplier", {})
        if not isinstance(mm, dict):
            errors.append("pricing_policy.market_multiplier must be a mapping")
        else:
            unknown = set(mm) - SUPPORTED_MARKETS
            if unknown:
                errors.append(f"unsupported markets in market_multiplier: {sorted(unknown)}")

    # services / offers unique ids
    for key, tier_key, tiers in (
        ("services", "type", SERVICE_TYPES),
        ("offers", "tier", OFFER_TIERS),
    ):
        items = data.get(key)
        if not isinstance(items, list):
            errors.append(f"{key} must be a list")
            continue
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                errors.append(f"{key} entries must be mappings")
                continue
            iid = item.get("id")
            if not iid:
                errors.append(f"{key} entry missing id")
            elif iid in seen:
                errors.append(f"duplicate {key} id: {iid}")
            else:
                seen.add(iid)
            if tier_key in item and item[tier_key] not in tiers:
                errors.append(f"{key}.{iid} has invalid {tier_key}: {item.get(tier_key)}")

    # markets
    mp = data.get("market_profiles")
    if isinstance(mp, dict):
        unknown = set(mp) - SUPPORTED_MARKETS
        if unknown:
            errors.append(f"unsupported market_profiles: {sorted(unknown)}")

    # claims must be lists of strings
    for claim_key in ("approved_claims", "forbidden_claims", "claims_requiring_verification"):
        claims = data.get(claim_key)
        if claims is None:
            continue
        if not isinstance(claims, list) or not all(isinstance(c, str) for c in claims):
            errors.append(f"{claim_key} must be a list of strings")

    return errors
