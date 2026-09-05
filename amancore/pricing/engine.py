"""Pricing Engine — deterministic, driven by Business Brain policy.

The AI may reason about scope; deterministic functions calculate the price,
policy controls it, and the owner approves it.
"""

from __future__ import annotations

from ..functions.pricing import (
    RISK_FACTOR,
    calculate_base_target,
    calculate_minimum_approved,
    calculate_negotiation_range,
    calculate_payment_fee,
    calculate_target_price,
    calculate_true_cost,
    validate_pricing,
)
from . import registry

_DEFAULT_PAYMENT_PROFILE = {"percentage_fee": 0.03, "fixed_fee": 0.0}


class PricingEngine:
    def __init__(self, brain_store, payment_fee_profiles: dict | None = None, price_validity_days: int = 14, router=None):
        self.brain_store = brain_store
        self.payment_fee_profiles = payment_fee_profiles or {}
        self.price_validity_days = price_validity_days
        self.router = router

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def price(self, scope: dict, opportunity_id: str | None = None) -> dict:
        policy = self.brain.get("pricing_policy", {})
        service = scope.get("service")
        market = scope.get("market") or "indonesia"
        markets = self.brain.get("market_profiles", {})
        known_services = {s["id"] for s in self.brain.get("services", [])}
        known_markets = set(markets)
        known_currencies = {m.get("currency") for m in markets.values() if m.get("currency")}
        currency = scope.get("currency") or markets.get(market, {}).get("currency", "USD")

        hours = scope.get("estimated_hours") or scope.get("total_estimated_hours") or 0
        # Approved add-ons add deterministic hours on top of the base scope.
        for aid in scope.get("add_ons") or []:
            hours += registry.addon_hours(self.brain, aid)
        shadow_rate = policy.get("shadow_rate", 40)
        revision_rate = policy.get("revision_reserve", 0.15)
        risk = scope.get("risk_level", "medium")
        risk_rate = policy.get("risk_reserve", 0.15) * RISK_FACTOR.get(risk, 1.0)
        external = scope.get("external_costs") or 0
        infra = scope.get("infrastructure_costs") or 0
        key = registry.policy_key(self.brain, service)
        markup = policy.get("markup_by_service", {}).get(key,
                  policy.get("markup_by_service", {}).get(service, 3.0))
        market_mult = policy.get("market_multiplier", {}).get(market, 1.0)
        min_mult = policy.get("minimum_approved_multiplier", {}).get(key,
                    policy.get("minimum_approved_multiplier", {}).get(service, 1.3))

        profile = self.payment_fee_profiles.get(market) or self.payment_fee_profiles.get("default") or _DEFAULT_PAYMENT_PROFILE
        rough_price = (hours * shadow_rate) * markup * market_mult
        payment_fees = calculate_payment_fee(rough_price, profile)

        cost = calculate_true_cost(hours, shadow_rate, external, infra, payment_fees, revision_rate, risk_rate)
        base_target = calculate_base_target(cost["true_cost"], markup)
        target = calculate_target_price(base_target, market_mult)
        minimum = calculate_minimum_approved(cost["true_cost"], min_mult)
        floor, _hi = calculate_negotiation_range(target, minimum)

        errors = validate_pricing(
            estimated_hours=hours,
            service=service,
            market=market,
            markup=markup,
            minimum_approved=minimum,
            target_price=target,
            cost_floor=cost["cost_floor"],
            currency=currency,
            known_services=known_services,
            known_markets=known_markets,
            known_currencies=known_currencies,
        )
        confidence = self._confidence(scope, errors)
        warnings = list(errors)
        if confidence == "low" and not errors:
            warnings.append("pricing_warning: low confidence")

        return {
            "project_id": opportunity_id,
            "service": service,
            "market": market,
            "currency": currency,
            "estimated_hours": hours,
            **cost,
            "base_target": base_target,
            "market_multiplier": market_mult,
            "target_price": target,
            "minimum_approved": minimum,
            "negotiation_floor": floor,
            "negotiation_range": [floor, target],
            "pricing_policy_version": "v1",
            "pricing_brain_version": self.brain_store.current()[0],
            "confidence": confidence,
            "warnings": warnings,
            "breakdown": {
                "shadow_rate": shadow_rate,
                "markup": markup,
                "minimum_multiplier": min_mult,
                "risk": risk,
                "risk_reserve_rate": round(risk_rate, 3),
                "payment_profile": profile,
                "price_validity_days": self.price_validity_days,
            },
        }

    @staticmethod
    def _confidence(scope: dict, errors: list[str]) -> str:
        if errors:
            return "low"
        if not scope.get("estimated_hours"):
            return "low"
        if not (scope.get("scope") or scope.get("included")):
            return "medium"
        return "high"
