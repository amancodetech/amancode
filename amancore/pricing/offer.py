"""Shared offer selection — used by Sales Agent and Pricing/Offer Agent."""

from __future__ import annotations

from . import registry

_OFFER_FOR_SERVICE = {
    "business_website_system": "website_system",
    "custom_web_application": "web_app",
    "business_system_mini_erp": "mini_erp",
    "mobile_app": "mobile_app",
}


def select_offer(brain: dict, qual: dict) -> dict:
    need = " ".join(str(x) for x in [qual.get("need"), qual.get("scope"), qual.get("outcome")]).lower()
    if any(k in need for k in ["app", "mobile", "تطبيق", "aplikasi"]):
        service_id = "mobile_app"
    elif any(k in need for k in ["erp", "inventory", "manage", "accounting", "محاسبة", "مخزون", "نظام", "sistem"]):
        service_id = "business_system_mini_erp"
    elif any(k in need for k in ["portal", "custom", "منصة", "web app", "aplikasi web"]):
        service_id = "custom_web_application"
    else:
        service_id = "business_website_system"

    services = {s["id"]: s for s in brain.get("services", [])}
    offers = {o["id"]: o for o in brain.get("offers", [])}
    service = services.get(service_id, {"name": service_id})
    # Single source for service→offer identity (registry, not a local map).
    offer_id = registry.offer_for_service(brain, service_id) \
        or _OFFER_FOR_SERVICE.get(service_id, "website_system")
    offer = offers.get(offer_id, {"name": offer_id})
    return {
        "service": service_id,
        "service_name": service.get("name"),
        "offer": offer_id,
        "offer_name": offer.get("name"),
        "reason": f"matches stated need",
        "missing_information": qual.get("missing_information"),
        "confidence": "medium",
    }


def recommendation_message(rec: dict, fit: str = "good") -> str:
    return (
        f"Based on what you've shared, I recommend our {rec.get('service_name', 'solution')}. "
        f"It fits your needs well — shall I prepare the next step?"
    )
