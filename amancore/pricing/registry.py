"""Pricing Registry — the SINGLE source of Service→Offer→PricingProfile identity.

Every module that used to keep its own scattered map (_SERVICE_POLICY_KEY,
_BASE_HOURS, _COMPLEXITY_MULT, _SERVICE_FOR_OFFER, _CATEGORY_SERVICE) now
resolves through here. All business values (base hours, complexity factors,
offer linkage, add-ons) come from Business Brain `pricing_profiles` /
`services` / `add_ons`; the constants below are conservative fallbacks only,
isolated in one place so nothing else in the codebase ever guesses again.

The LLM never touches this module and it never reads from prompts/configs
outside the Brain.
"""

from __future__ import annotations

# Category → canonical service id (conversation categories map to catalog).
CATEGORY_SERVICE = {
    "website": "business_website_system",
    "ecommerce": "ecommerce_store",
    "mobile": "mobile_app",
    "business_system": "business_system_mini_erp",
    "automation": "ai_automation_suite",
}

# D3-A — conversation category → RIL coverage tier. Pure map; unknown/None
# falls back to "website" (previous hardcoded behavior) + caller audits.
CATEGORY_TIER = {
    "website": "website",
    "ecommerce": "website",
    "mobile": "mobile",
    "business_system": "mini_erp",
    "automation": "web_app",
}


def tier_for_category(category: str | None) -> str:
    """RIL tier for a conversation category (default "website")."""
    return CATEGORY_TIER.get(category or "", "website")

# Service → offer id (the offer that carries the price for that service).
SERVICE_OFFER = {
    "business_website_system": "website_system",
    "custom_web_application": "web_app",
    "business_system_mini_erp": "mini_erp",
    "mobile_app": "mobile_app",
    "ecommerce_store": "ecommerce_store",
    "ai_automation_suite": "ai_automation",
}

# Fallback hours when the Brain carries no profile (never a guess source).
_FALLBACK_BASE_HOURS = {
    "business_website_system": 20,
    "custom_web_application": 60,
    "business_system_mini_erp": 120,
    "mobile_app": 100,
    "ecommerce_store": 70,
    "ai_automation_suite": 80,
}

# Service → pricing_policy key. The Brain's markup/minimum tables use their
# own stable alias (e.g. `website_standard`), distinct from both the service
# id and the offer id. The authoritative value lives in
# `pricing_profiles[service].policy_key`; this map is only a fallback.
_POLICY_KEY = {
    "business_website_system": "website_standard",
    "custom_web_application": "web_app",
    "business_system_mini_erp": "business_system",
    "mobile_app": "mobile",
    "ecommerce_store": "website_standard",
    "ai_automation_suite": "business_system",
}

# Conservative fallback complexity multipliers (Brain overrides).
_FALLBACK_COMPLEXITY = {"low": 1.0, "medium": 1.25, "high": 1.6}


def service_for_category(brain: dict, category: str | None) -> str | None:
    if not category:
        return None
    # Brain may map category→service explicitly; else use the canonical map.
    explicit = (brain.get("service_categories") or {}).get(category)
    if isinstance(explicit, dict) and explicit.get("service_id"):
        return explicit["service_id"]
    return CATEGORY_SERVICE.get(category)


def offer_for_service(brain: dict, service: str | None) -> str | None:
    if not service:
        return None
    for svc in (brain.get("services") or []):
        if svc.get("id") == service and svc.get("offer_id"):
            return svc["offer_id"]
    return SERVICE_OFFER.get(service)


def policy_key(brain: dict, service: str | None) -> str:
    """Key into `pricing_policy.markup_by_service` / `minimum_approved_multiplier`.
    Brain pricing_profiles are authoritative; the map is a legacy fallback."""
    prof = profile_for_service(brain, service)
    pk = prof.get("policy_key")
    if pk:
        return str(pk)
    return _POLICY_KEY.get(service or "", service or "")


def profile_for_service(brain: dict, service: str | None) -> dict:
    profiles = brain.get("pricing_profiles") or {}
    if isinstance(profiles, dict) and service:
        prof = profiles.get(service)
        if isinstance(prof, dict):
            return prof
    return {}


def base_hours(brain: dict, service: str | None) -> float:
    prof = profile_for_service(brain, service)
    h = prof.get("base_hours")
    if isinstance(h, (int, float)) and h > 0:
        return float(h)
    for svc in (brain.get("services") or []):
        bh = svc.get("base_hours")
        if svc.get("id") == service and isinstance(bh, (int, float)) and bh > 0:
            return float(bh)
    return float(_FALLBACK_BASE_HOURS.get(service, 20))


def complexity_multiplier(brain: dict, service: str | None, level: str) -> float:
    prof = profile_for_service(brain, service)
    cm = prof.get("complexity_mult") or {}
    if isinstance(cm, dict) and cm.get(level):
        return float(cm[level])
    return float(_FALLBACK_COMPLEXITY.get(level, 1.25))


def complexity_level(features: dict | None) -> str:
    """Deterministic complexity from a feature set. Progressive: works with
    partial info — missing fields simply add nothing. Returns low/medium/high."""
    features = features or {}
    score = 0
    score += min(3, max(0, int(features.get("pages") or 0) - 5))         # >5 pages
    score += 1 if features.get("dynamic_content") else 0
    score += 1 if (int(features.get("languages") or 1) > 1) else 0
    score += 1 if features.get("forms") else 0
    score += 1 if features.get("booking") else 0
    score += 2 if features.get("payments") else 0
    score += 1 if features.get("integrations") else 0
    score += 1 if features.get("cms_admin") else 0
    score += 2 if features.get("custom_dashboards") else 0
    score += 1 if features.get("advanced_search") else 0
    score += 2 if features.get("member_areas") else 0
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def add_ons(brain: dict) -> list[dict]:
    adds = brain.get("add_ons")
    return adds if isinstance(adds, list) else []


def add_on(brain: dict, addon_id: str) -> dict | None:
    for a in add_ons(brain):
        if a.get("id") == addon_id:
            return a
    return None


def compatible_add_ons(brain: dict, service: str | None,
                       requested: list[str]) -> dict:
    """Validate a requested set of add-on ids against compatibility rules.
    Returns {'valid': [...], 'invalid': [...], 'reasons': {...}} — never lets
    the AI decide compatibility."""
    catalog = {a["id"]: a for a in add_ons(brain)}
    valid, invalid, reasons = [], [], {}
    for aid in requested or []:
        spec = catalog.get(aid)
        if spec is None:
            invalid.append(aid)
            reasons[aid] = "unknown add-on"
            continue
        compatible = spec.get("compatible_with")
        if isinstance(compatible, list) and compatible and service not in compatible:
            invalid.append(aid)
            reasons[aid] = f"not compatible with service {service}"
            continue
        incompatible = spec.get("incompatible_with")
        if isinstance(incompatible, list) and incompatible and service in incompatible:
            invalid.append(aid)
            reasons[aid] = f"incompatible with service {service}"
            continue
        requires = spec.get("requires")
        if isinstance(requires, list) and requires:
            missing = [r for r in requires if r not in (requested or [])]
            if missing:
                invalid.append(aid)
                reasons[aid] = f"requires {', '.join(missing)}"
                continue
        valid.append(aid)
    return {"valid": valid, "invalid": invalid, "reasons": reasons}


def addon_hours(brain: dict, addon_id: str) -> float:
    spec = add_on(brain, addon_id) or {}
    h = spec.get("base_hours")
    return float(h) if isinstance(h, (int, float)) and h >= 0 else 0.0


_SCOPE_KEYS = (
    "scope", "key_features", "timeline", "pages", "languages", "forms",
    "booking", "payments", "integrations", "cms_admin", "custom_dashboards",
    "advanced_search", "member_areas", "dynamic_content", "product_count",
    "users", "modules", "workflows",
)


def scope_fingerprint(category: str | None, facts: dict | None,
                      small: bool = False, add_ons: list[str] | None = None) -> str:
    """Deterministic fingerprint of a pricing scope. If the customer changes
    scope, the fingerprint changes and the previous approved snapshot must be
    superseded — a new approval is required. Only stable scope facts feed it,
    so it reproduces exactly for the same inputs."""
    import hashlib
    import json

    facts = facts or {}
    parts = [category or "", "small" if small else "std"]
    for key in _SCOPE_KEYS:
        val = facts.get(key)
        if isinstance(val, list):
            val = sorted(str(v) for v in val)
        if val not in (None, "", [], {}, 0):
            parts.append(f"{key}={val}")
    for aid in sorted(add_ons or []):
        parts.append(f"addon={aid}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def calculate_dynamic_hours(brain: dict, service: str | None, facts: dict | None,
                            small: bool = False) -> float:
    """Calculate project hours completely dynamically based on client facts:
    pages, language count, dashboard depth, integrations, catalog size, and complexity.
    Never a rigid flat number."""
    facts = facts or {}
    base = base_hours(brain, service)
    if small and service in ("business_website_system", "website"):
        base = 6.0

    # 1. Page scaling (pages designed and coded beyond the baseline of 5)
    pages = 0
    try:
        raw_pages = facts.get("pages") or facts.get("page_count")
        if raw_pages:
            pages = int(str(raw_pages).strip())
    except (ValueError, TypeError):
        pages = 0
    if pages > 5:
        extra_pages = min(pages - 5, 50)
        page_rate = 2.0 if service in ("business_website_system", "ecommerce_store", "website") else 3.0
        base += extra_pages * page_rate

    # 2. Dynamic Complexity multiplier (low: 1.0, medium: 1.25, high: 1.6)
    c_level = complexity_level(facts)
    c_mult = complexity_multiplier(brain, service, c_level)
    hours = base * c_mult

    # 3. Multilingual dynamic scaling (RTL/LTR mirror + i18n translation keys: 15% per extra language)
    lang_count = 1
    raw_langs = facts.get("languages") or facts.get("language_count")
    if isinstance(raw_langs, list):
        lang_count = max(1, len(raw_langs))
    elif raw_langs:
        try:
            lang_count = max(1, int(raw_langs))
        except (ValueError, TypeError):
            lang_count = 1
    if lang_count > 1:
        hours += hours * (0.15 * (lang_count - 1))

    # 4. Payment Gateways: each additional gateway requires webhook, IPN, and testing (+6h per extra gateway)
    gateways_count = 0
    raw_gw = facts.get("payment_gateways") or facts.get("gateways")
    if isinstance(raw_gw, list):
        gateways_count = len(raw_gw)
    elif raw_gw:
        try:
            gateways_count = int(raw_gw)
        except (ValueError, TypeError):
            gateways_count = 1
    if gateways_count > 1:
        hours += (gateways_count - 1) * 6.0

    # 5. Dashboard / Admin depth dynamic scaling (CMS vs Orders & Invoicing vs Full RBAC ERP)
    dashboard_type = str(facts.get("dashboard_type") or facts.get("dashboard") or "").lower()
    if "erp" in dashboard_type or "full" in dashboard_type or facts.get("custom_dashboards"):
        # Full ERP dashboard: RBAC roles, inventory, financial analytics
        hours += 30.0 * (1.2 if c_level == "high" else 1.0)
    elif "orders" in dashboard_type or "invoicing" in dashboard_type or facts.get("custom_dashboard"):
        # Operations dashboard: orders, receipts, invoice generation
        hours += 15.0
    elif facts.get("erp_modules") or facts.get("modules"):
        try:
            mod_count = len(facts.get("modules") or []) if isinstance(facts.get("modules"), list) else int(facts.get("modules") or 1)
            hours += max(0, mod_count) * 12.0
        except (ValueError, TypeError):
            hours += 15.0

    # 6. Explicit add-ons (booking, notifications, shipping integrations)
    for aid in facts.get("add_ons") or []:
        hours += addon_hours(brain, aid)

    return round(max(6.0, hours), 1)

