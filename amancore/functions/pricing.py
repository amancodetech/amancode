"""Deterministic pricing functions. No LLM. No commission."""

from __future__ import annotations

RISK_FACTOR = {"low": 0.7, "medium": 1.0, "high": 1.5, "critical": 2.0}


def calculate_true_cost(
    estimated_hours: float,
    shadow_rate: float,
    external_costs: float = 0.0,
    infrastructure_costs: float = 0.0,
    payment_fees: float = 0.0,
    revision_reserve_rate: float = 0.15,
    risk_reserve_rate: float = 0.15,
) -> dict:
    founder_cost = estimated_hours * shadow_rate
    revision_reserve = founder_cost * revision_reserve_rate
    risk_reserve = (founder_cost + external_costs + infrastructure_costs) * risk_reserve_rate
    true_cost = (
        founder_cost + external_costs + infrastructure_costs
        + payment_fees + revision_reserve + risk_reserve
    )
    return {
        "founder_cost": round(founder_cost, 2),
        "external_costs": round(external_costs, 2),
        "infrastructure_costs": round(infrastructure_costs, 2),
        "payment_fees": round(payment_fees, 2),
        "revision_reserve": round(revision_reserve, 2),
        "risk_reserve": round(risk_reserve, 2),
        "true_cost": round(true_cost, 2),
        "cost_floor": round(true_cost, 2),
    }


def calculate_base_target(true_cost: float, markup: float) -> float:
    return round(true_cost * markup, 2)


def calculate_target_price(base_target: float, market_multiplier: float, value_adjustment: float = 1.0) -> float:
    return round(base_target * market_multiplier * value_adjustment, 2)


def calculate_minimum_approved(true_cost: float, minimum_multiplier: float) -> float:
    return round(true_cost * minimum_multiplier, 2)


def calculate_negotiation_range(target_price: float, minimum_approved: float) -> tuple[float, float]:
    lo, hi = sorted((minimum_approved, target_price))
    return (lo, hi)


def calculate_payment_fee(price_estimate: float, profile: dict) -> float:
    pct = profile.get("percentage_fee", 0.0)
    fixed = profile.get("fixed_fee", 0.0)
    return round(price_estimate * pct + fixed, 2)


def calculate_discount(previous_price: float, new_price: float, reason: str, scope_change: str = "") -> dict:
    pct = round((previous_price - new_price) / previous_price * 100, 2) if previous_price else 0.0
    return {
        "previous_price": round(previous_price, 2),
        "new_price": round(new_price, 2),
        "percentage": pct,
        "reason": reason,
        "scope_change": scope_change,
        "approver": "owner",
    }


def validate_pricing(**inputs) -> list[str]:
    errors: list[str] = []
    for key, value in inputs.items():
        if isinstance(value, (int, float)) and value < 0:
            errors.append(f"{key} must be non-negative")
    if inputs.get("estimated_hours") is not None and inputs["estimated_hours"] > 5000:
        errors.append("estimated_hours implausible")
    if inputs.get("service") and inputs.get("known_services") and inputs["service"] not in inputs["known_services"]:
        errors.append(f"unknown service: {inputs['service']}")
    if inputs.get("market") and inputs.get("known_markets") and inputs["market"] not in inputs["known_markets"]:
        errors.append(f"unknown market: {inputs['market']}")
    if inputs.get("markup") is not None and inputs["markup"] < 1.0:
        errors.append("markup must be >= 1.0")
    if (
        inputs.get("minimum_approved") is not None
        and inputs.get("target_price") is not None
        and inputs["minimum_approved"] > inputs["target_price"]
    ):
        errors.append("minimum_approved > target_price")
    if (
        inputs.get("target_price") is not None
        and inputs.get("cost_floor") is not None
        and inputs["target_price"] < inputs["cost_floor"]
    ):
        errors.append("target_price < cost_floor")
    if inputs.get("currency") and inputs.get("known_currencies") and inputs["currency"] not in inputs["known_currencies"]:
        errors.append(f"invalid currency: {inputs['currency']}")
    return errors
