"""Negotiation Engine — reduce scope before reduce price. Deterministic where possible."""

from __future__ import annotations

from ..functions.pricing import calculate_discount


class NegotiationEngine:
    def __init__(self, pricing_engine, dispatcher=None):
        self.pricing_engine = pricing_engine
        self.dispatcher = dispatcher

    def scope_reduction(self, scope: dict) -> dict:
        """Remove optional features and reduce hours → smaller scope."""
        optional = list(scope.get("optional_features", []))
        included = [f for f in scope.get("included", []) if f not in optional]
        hours = scope.get("estimated_hours") or 0
        reduced_hours = round(hours * 0.75) if optional else hours
        reduced = dict(scope)
        reduced["included"] = included
        reduced["estimated_hours"] = reduced_hours
        reduced["reduced_features"] = optional
        reduced["offer_candidate"] = scope.get("smaller_offer") or "Business Presence Starter"
        return reduced

    def evaluate_budget(self, budget, pricing_result) -> dict:
        """Compare a customer budget to the pricing zone (no arbitrary discount)."""
        if budget is None:
            return {"action": "ask_for_scope", "escalation": False, "below_minimum": False}
        if budget < pricing_result["minimum_approved"]:
            return {
                "action": "owner_approval",
                "escalation": True,
                "below_minimum": True,
                "message": "This budget is below our minimum approved price — requires owner decision.",
            }
        if budget >= pricing_result["target_price"]:
            return {"action": "proceed", "escalation": False, "below_minimum": False, "fits": True}
        return {
            "action": "negotiate_within_zone",
            "escalation": False,
            "below_minimum": False,
            "zone": pricing_result.get("negotiation_range"),
        }

    def on_price_objection(self, scope: dict, pricing_result: dict, message: str = "") -> dict:
        """Golden rule: clarify → value → scope reduction → smaller offer → recalc → zone → minimum."""
        reduced_scope = self.scope_reduction(scope)
        new_pricing = self.pricing_engine.price(reduced_scope, pricing_result.get("project_id"))
        price_moved = new_pricing["target_price"] < pricing_result["target_price"]
        discount = None
        escalation_required = False
        if new_pricing["target_price"] < pricing_result["minimum_approved"]:
            escalation_required = True
        if price_moved:
            discount = calculate_discount(
                pricing_result["target_price"],
                new_pricing["target_price"],
                reason="scope reduction",
                scope_change="reduced optional features",
            )
        return {
            "steps": ["clarify", "value_reframe", "scope_reduction", "smaller_offer", "recalculate"],
            "reduced_scope": reduced_scope,
            "new_pricing": new_pricing,
            "price_moved": price_moved,
            "discount": discount,
            "escalation_required": escalation_required,
            "message": (
                "We can reduce the scope to fit your budget while keeping the core result — "
                "the price is calculated from the reduced scope."
            ),
        }
