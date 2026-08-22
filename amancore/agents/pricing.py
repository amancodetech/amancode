"""Pricing/Offer Agent — scope analysis, pricing interpretation, negotiation
strategy, proposal draft. No final-price authority, no external sending.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..pricing.offer import recommendation_message, select_offer
from ..services.claim_gate import FORBIDDEN, ClaimGate
from ..services.policy import PolicyEngine
from ..services.risk import RiskEngine
from .base import Agent

_BASE_HOURS = {
    "business_website_system": 20,
    "custom_web_application": 60,
    "business_system_mini_erp": 120,
    "mobile_app": 100,
}
_COMPLEXITY_MULT = {"low": 1.0, "medium": 1.25, "high": 1.6}


class PricingOfferAgent(Agent):
    def __init__(
        self,
        brain_store,
        crm,
        pricing_engine,
        negotiation_engine,
        snapshot_store,
        proposal_generator,
        proposal_store,
        approvals=None,
        **kw,
    ):
        super().__init__("pricing", brain_store, crm=crm, **kw)
        self.pricing_engine = pricing_engine
        self.negotiation_engine = negotiation_engine
        self.snapshot_store = snapshot_store
        self.proposal_generator = proposal_generator
        self.proposal_store = proposal_store
        self.approvals = approvals
        self.risk = RiskEngine()
        self.policy = PolicyEngine()
        self.claim_gate = ClaimGate(brain_store)

    # ---- scope ---------------------------------------------------------
    def analyze_scope(self, opportunity: dict, lead: dict, conversation: dict) -> dict:
        service = opportunity.get("service") or "business_website_system"
        base_hours = _BASE_HOURS.get(service, 20)
        summary = str(opportunity.get("scope_summary") or "")
        complexity = "high" if len(summary) > 120 else ("medium" if len(summary) > 40 else "low")
        facts = conversation.get("facts", {})
        integrations = len(facts.get("integrations") or []) if isinstance(facts.get("integrations"), list) else 0
        languages = max(1, len(facts.get("languages") or []) if isinstance(facts.get("languages"), list) else 1)
        estimated_hours = round(base_hours * _COMPLEXITY_MULT.get(complexity, 1.25) * (1 + 0.10 * integrations + 0.15 * (languages - 1)))
        risk_level = "high" if service in ("business_system_mini_erp", "custom_web_application", "mobile_app") or integrations > 3 else "medium"
        return {
            "service": service,
            "market": lead.get("market") or "indonesia",
            "included": [opportunity.get("scope_summary")] if opportunity.get("scope_summary") else [],
            "excluded": [],
            "optional_features": [],
            "deliverables": ["delivery", "documentation", "warranty"],
            "assumptions": ["content provided by client"],
            "complexity": complexity,
            "integration_count": integrations,
            "language_count": languages,
            "estimated_hours": estimated_hours,
            "risk_level": risk_level,
            "missing_information": ["timeline", "final content"] if not opportunity.get("scope_summary") else [],
            "confidence": "high" if opportunity.get("scope_summary") else "medium",
        }

    # ---- flow ----------------------------------------------------------
    def analyze_and_price(self, opportunity_id: str) -> dict:
        opportunity = self.crm.get_opportunity(opportunity_id)
        if opportunity is None:
            raise ValueError(f"opportunity {opportunity_id} not found")
        lead = self.crm.get_lead(opportunity["lead_id"]) or {}
        conversation = {"facts": {}}

        scope = self.analyze_scope(opportunity, lead, conversation)
        self._emit("scope.analyzed", {"opportunity_id": opportunity_id, "scope": scope})

        qual = {"need": opportunity.get("scope_summary") or "", "scope": "", "outcome": ""}
        offer = select_offer(self.brain, qual)

        pricing_result = self.pricing_engine.price(scope, opportunity_id)
        self._emit("price.calculated", {"opportunity_id": opportunity_id, "pricing_result": pricing_result})

        risk = self.risk.classify("price.calculated")
        decision = self.policy.evaluate(self.brain, "price.calculated", risk)
        approval_id = None
        if self.approvals is not None:
            approval_id = self.approvals.create_approval_request(
                type_="final_price",
                requested_by="pricing_agent",
                risk_level=risk,
                reason=f"final price requires owner ({decision.action})",
                payload={"opportunity_id": opportunity_id, "target_price": pricing_result["target_price"]},
                policy_reference=decision.policy_reference,
            )
            self._emit("pricing.approval_requested", {"approval_id": approval_id}, risk_level=risk)

        self._audit("pricing.analyzed", "opportunity", result=opportunity_id)
        return {
            "scope_analysis": scope,
            "offer": offer,
            "pricing_result": pricing_result,
            "approval_required": True,
            "approval_id": approval_id,
            "warning": bool(pricing_result["warnings"]),
        }

    def finalize(self, approval_id: str, approved_by: str) -> dict:
        approval = self.approvals.get(approval_id) if self.approvals else None
        if approval is None or approval["status"] != "approved":
            raise PermissionError("price not approved yet")
        payload = approval.get("payload") or "{}"
        import json

        data = json.loads(payload) if isinstance(payload, str) else payload
        opportunity_id = data.get("opportunity_id")
        opportunity = self.crm.get_opportunity(opportunity_id)
        lead = self.crm.get_lead(opportunity["lead_id"]) if opportunity else {}
        scope = self.analyze_scope(opportunity, lead, {"facts": {}}) if opportunity else {}
        pricing_result = self.pricing_engine.price(scope, opportunity_id)

        expiration = (datetime.now(timezone.utc) + timedelta(days=self.pricing_engine.price_validity_days)).isoformat()
        snapshot_id = self.snapshot_store.create(
            opportunity_id,
            pricing_result,
            approved_price=pricing_result["target_price"],
            approved_by=approved_by,
            business_brain_version=self.brain_store.current()[0],
            expiration_at=expiration,
        )
        if opportunity:
            self.crm.update_opportunity(opportunity_id, pricing_status="approved", stage="offer_recommended")
        self._emit("pricing.approved", {"opportunity_id": opportunity_id, "snapshot_id": snapshot_id})
        self._emit("pricing.snapshot_created", {"snapshot_id": snapshot_id})
        self._audit("pricing.approved", "pricing", result=snapshot_id)
        return {"snapshot_id": snapshot_id, "pricing_result": pricing_result}

    def draft_proposal(self, opportunity_id: str, snapshot_id: str) -> dict:
        opportunity = self.crm.get_opportunity(opportunity_id)
        lead = self.crm.get_lead(opportunity["lead_id"]) if opportunity else {}
        scope = self.analyze_scope(opportunity, lead, {"facts": {}})
        qual = {"need": opportunity.get("scope_summary") or "", "scope": "", "outcome": ""}
        offer = select_offer(self.brain, qual)
        snapshot = self.snapshot_store.get(snapshot_id)

        proposal = self.proposal_generator.generate(
            opportunity,
            scope,
            offer,
            snapshot or {},
            timeline=scope.get("timeline", ""),
            terms={"payment_terms": "50% upfront, 50% on delivery"},
        )
        # claim safety
        rendered = self.proposal_generator.render(proposal)
        claim = self.claim_gate.check(rendered)
        if claim.status == FORBIDDEN:
            proposal["status"] = "rejected"
            self._emit("proposal.rejected", {"proposal_id": proposal.get("id")})
            return {"proposal_id": proposal.get("id"), "status": "rejected", "reason": "forbidden claim"}

        proposal_id = self.proposal_store.create(opportunity_id, proposal["body"], snapshot_id, self.brain_store.current()[0])
        approval_id = None
        if self.approvals is not None:
            approval_id = self.approvals.create_approval_request(
                type_="proposal_review",
                requested_by="pricing_agent",
                risk_level="high",
                reason="proposal review required",
                payload={"proposal_id": proposal_id},
                policy_reference="proposal_policy",
            )
        self.proposal_store.update(proposal_id, status="review")
        self._emit("proposal.created", {"proposal_id": proposal_id})
        self._emit("proposal.review_requested", {"proposal_id": proposal_id})
        self._audit("proposal.drafted", "proposal", result=proposal_id)
        return {"proposal_id": proposal_id, "status": "review", "approval_id": approval_id}
