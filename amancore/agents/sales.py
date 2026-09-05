"""Sales Agent — conversation intelligence (no external send, no pricing)."""

from __future__ import annotations

import json

from ..functions.lead_scoring import score as score_lead
from ..ids import new_id, utcnow
from ..pricing.offer import recommendation_message, select_offer
from ..sales.conversation_memory import extract_facts
from ..sales.fit import compute_fit
from ..sales.state_machine import InvalidTransition, transition
from .base import Agent


class SalesAgent(Agent):
    def __init__(
        self,
        brain_store,
        crm,
        conversation_memory,
        discovery,
        qualification,
        objection_skill,
        followup,
        handoff,
        **kw,
    ):
        super().__init__("sales", brain_store, crm=crm, **kw)
        self.conversation_memory = conversation_memory
        self.discovery = discovery
        self.qualification = qualification
        self.objection_skill = objection_skill
        self.followup = followup
        self.handoff = handoff

    def process_message(self, lead: dict, message: str, history: str = "") -> dict:
        lead_id = lead["lead_id"]
        corr = new_id()
        mem = self.conversation_memory.get_or_create(lead_id, "internal", lead.get("language", "en"))
        if mem["current_state"] == "new":
            self._emit("sales.conversation_started", {"lead_id": lead_id}, corr)
        mem["current_state"] = self._advance(mem["current_state"])

        facts = extract_facts(message, self.router, history=history)
        # CIR interpretation rides along ephemerally (in-turn only): popped
        # before merge so it can never persist into facts/requirements.
        cir_block = facts.pop("cir", None)
        mem = self.conversation_memory.merge_facts(mem, facts)
        mem["last_message_at"] = utcnow()

        # human handoff
        trigger = self.handoff.detect(message)
        if trigger:
            h = self.handoff.request(lead, mem, trigger)
            self.conversation_memory.save(mem)
            self._emit("sales.handoff_requested", {"reason": trigger}, corr)
            self._audit("sales.handoff_requested", "lead", result=trigger)
            return {
                "reply": "I'll connect you with a specialist to help with this.",
                "state": mem["current_state"], "handoff": h, "needs_human": True,
                "cir": cir_block,
            }

        # objection
        obj = self.objection_skill.classify(message)
        if obj:
            resp = self.objection_skill.handle(obj, self.brain)
            if obj not in mem["objections"]:
                mem["objections"].append(obj)
            self._emit("objection.detected", {"objection": obj}, corr)
            self.conversation_memory.save(mem)
            return {
                "reply": resp["clarification"], "objection": obj,
                "objection_response": resp, "state": mem["current_state"],
                "cir": cir_block,
            }

        fit = compute_fit(self.brain, self._lead_data(lead))
        engagement = self._engagement(mem["current_state"])
        qual = self.qualification.qualify(mem, lead, fit, engagement=engagement)

        # still discovering
        if not qual["decision_readiness"]:
            question = self.discovery.next_question(mem)
            mem["current_state"] = "discovery"
            mem["next_action"] = "ask_next_question"
            self.conversation_memory.save(mem)
            self._emit("sales.discovery_updated", {"missing": qual["missing_information"]}, corr)
            return {
                "reply": question, "state": mem["current_state"],
                "qualification": qual, "next_question": question,
                "cir": cir_block,
            }

        # qualified → score + recommend + opportunity
        try:
            mem["current_state"] = transition("discovery", "qualified")
            mem["current_state"] = transition(mem["current_state"], "recommended")
        except InvalidTransition:
            mem["current_state"] = "offer_recommended"

        score_result = score_lead(qual)
        self.crm.update_lead(
            lead_id,
            lead_score=score_result["score"],
            lead_stage=score_result["category"],
            score_breakdown=json.dumps(score_result, ensure_ascii=False),
            fit_signals=json.dumps(fit, ensure_ascii=False),
        )
        self._emit("lead.scored", {"lead_id": lead_id, "score": score_result}, corr)
        self._emit("lead.stage_changed", {"lead_id": lead_id, "stage": score_result["category"]}, corr)

        rec = self._recommend(qual, fit)
        mem["next_action"] = "review_recommendation"
        self.conversation_memory.save(mem)
        self._emit("offer.recommended", {"lead_id": lead_id, "recommendation": rec}, corr)

        opp_id = self._upsert_opportunity(lead, rec, qual)
        self._audit("sales.offer_recommended", "lead", result=rec["service"])
        return {
            "reply": rec["message"], "state": mem["current_state"],
            "qualification": qual, "lead_score": score_result,
            "recommendation": rec, "opportunity_id": opp_id,
            "cir": cir_block,
        }

    def _advance(self, current: str) -> str:
        try:
            if current == "new":
                return transition("new", "first_message")
            if current == "contacted":
                return transition("contacted", "message")
            if current == "engaged":
                return transition("engaged", "discovery")
        except InvalidTransition:
            pass
        return current

    def _engagement(self, state: str) -> int:
        return {
            "new": 1, "contacted": 2, "engaged": 3,
            "discovery": 4, "qualification": 5, "offer_recommended": 5,
        }.get(state, 2)

    def _lead_data(self, lead: dict) -> dict:
        return {
            "market": lead.get("market"),
            "industry": lead.get("industry"),
            "website": lead.get("website"),
            "company": lead.get("company"),
            "service_fit": lead.get("service_interest"),
            "likely_needs": None,
        }

    def _recommend(self, qual: dict, fit: dict) -> dict:
        rec = select_offer(self.brain, qual)
        rec["fit"] = fit.get("overall_fit")
        rec["message"] = recommendation_message(rec, fit.get("overall_fit", "good"))
        return rec

    def _upsert_opportunity(self, lead: dict, rec: dict, qual: dict) -> str:
        common = {
            "offer_id": rec["offer"],
            "scope_summary": f"{qual.get('need', '')} / {qual.get('outcome', '')}",
            "stage": "offer_recommended",
        }
        existing = self.crm.get_opportunity_for_lead(lead["lead_id"])
        if existing:
            self.crm.update_opportunity(existing["opportunity_id"], service=rec["service"], **common)
            self._emit("opportunity.updated", {"opportunity_id": existing["opportunity_id"]})
            return existing["opportunity_id"]
        oid = self.crm.create_opportunity(lead["lead_id"], rec["service"], **common)
        self._emit("opportunity.created", {"opportunity_id": oid})
        return oid
