"""ICP fit engine — separate from lead score."""

from __future__ import annotations

_PRIMARY_INDUSTRY_KEYWORDS = ["service", "trading", "trade", "manufacturing", "retail", "logistics", "restaurant"]
_SECONDARY_INDUSTRY_KEYWORDS = ["export", "import", "distribution", "wholesale", "clinic", "real estate", "legal"]


def compute_fit(brain: dict, data: dict) -> dict:
    """Return {market_fit, industry_fit, service_fit, maturity_fit, overall_fit, reasons}."""
    reasons: list[str] = []
    market = (data.get("market") or "").lower()
    industry = (data.get("industry") or "").lower()

    market_fit = "high" if market in {m.lower() for m in brain.get("market_profiles", {})} else "low"
    if market_fit == "high":
        reasons.append("supported market")

    if any(k in industry for k in _PRIMARY_INDUSTRY_KEYWORDS):
        industry_fit = "high"
        reasons.append("primary ICP industry signal")
    elif any(k in industry for k in _SECONDARY_INDUSTRY_KEYWORDS):
        industry_fit = "high"
        reasons.append("secondary ICP industry signal")
    elif industry:
        industry_fit = "medium"
    else:
        industry_fit = "low"

    service_fit = "high" if (data.get("service_fit") or data.get("likely_needs")) else "low"
    if service_fit == "high":
        reasons.append("service/need signal")

    signals = data.get("digital_presence_signals") or {}
    if data.get("website") or signals:
        maturity_fit = "high"
        reasons.append("digital presence detected")
    elif data.get("company"):
        maturity_fit = "medium"
    else:
        maturity_fit = "low"

    if market_fit == "low":
        overall = "low"
    elif industry_fit == "high" or service_fit == "high":
        overall = "high"
    elif industry_fit == "medium" or maturity_fit == "high":
        overall = "medium"
    else:
        overall = "low"

    return {
        "market_fit": market_fit,
        "industry_fit": industry_fit,
        "service_fit": service_fit,
        "maturity_fit": maturity_fit,
        "overall_fit": overall,
        "reasons": reasons,
    }
