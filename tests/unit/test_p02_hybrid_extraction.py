"""P0-2 — Hybrid fact extraction is LIVE in the agent path.

Regex stays the fast path; the LLM "extraction" layer must now merge its
structured facts on top (when a router exists) and degrade silently to
regex-only when the provider fails. The planner's question engine must
respect LLM-captured facts immediately.
"""

from __future__ import annotations

import json
import unittest

from amancore.agents.sales import SalesAgent
from amancore.channels.handover import HandoverService
from amancore.conversation import ConversationModel
from amancore.crm.service import CRMService
from amancore.sales.conversation_memory import ConversationMemory
from amancore.sales.discovery import DiscoveryEngine
from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService
from amancore.sales.qualification import QualificationEngine
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.objection_handling import ObjectionHandlingSkill
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db


def _build_agent(db, brain, router):
    crm = CRMService(db)
    memory = ConversationMemory(crm)
    dispatcher = EventDispatcher()
    audit = AuditService(db)
    sales = SalesAgent(brain, crm, memory, DiscoveryEngine(), QualificationEngine(),
                       ObjectionHandlingSkill(brain), FollowupEngine(),
                       HandoffService(dispatcher), router=router,
                       audit=audit, dispatcher=dispatcher)
    return sales, crm, memory


class HybridExtractionTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)

    def test_llm_layer_merges_structured_facts(self):
        db = make_db(self.tmp / "h1.db")
        extraction = json.dumps({
            "scope": "donation portal + volunteer form",
            "timeline": "3 months",
            "budget": "$4000-6000",
            "authority": "association board",
            "languages": ["ar", "en"],
        })
        router = FakeRouter({"extraction": extraction})
        sales, crm, _mem = _build_agent(db, self.brain, router)
        lead_id = crm.create_lead(source_channel="whatsapp", contact_whatsapp="551100001")
        lead = crm.get_lead(lead_id)
        result = sales.process_message(lead, "نريد موقع جمعية مع بوابة تبرع")
        # LLM layer actually ran on the extraction task
        self.assertEqual(router.calls[0][0], "extraction")
        self.assertIn("scope", str(router.calls[0][1]))
        stored = ConversationMemory(crm).get_or_create(lead_id).get("facts") or {}
        self.assertEqual(stored.get("scope"), "donation portal + volunteer form")
        self.assertEqual(stored.get("budget"), "$4000-6000")
        self.assertEqual(stored.get("authority"), "association board")
        self.assertEqual(stored.get("timeline"), "3 months")

    def test_provider_failure_degrades_to_regex_only(self):
        class BoomRouter(FakeRouter):
            def route(self, task_class, messages, **kwargs):
                raise RuntimeError("provider down")

        db = make_db(self.tmp / "h2.db")
        sales, crm, _mem = _build_agent(db, self.brain, BoomRouter())
        lead_id = crm.create_lead(source_channel="whatsapp", contact_whatsapp="551100002")
        lead = crm.get_lead(lead_id)
        sales.process_message(lead, "I need it urgently, budget $5000, I am the owner")
        stored = ConversationMemory(crm).get_or_create(lead_id).get("facts") or {}
        self.assertIn("$5000", stored.get("budget", ""))
        self.assertEqual(stored.get("authority"), "owner/decision-maker")

    def test_routerless_stays_regex_only(self):  # legacy hatch intact
        db = make_db(self.tmp / "h3.db")
        sales, crm, _mem = _build_agent(db, self.brain, None)
        lead_id = crm.create_lead(source_channel="whatsapp", contact_whatsapp="551100003")
        lead = crm.get_lead(lead_id)
        sales.process_message(lead, "بدي موقع مع نظام حجوزات ونطاق ميزانية 3000 دولار")
        stored = ConversationMemory(crm).get_or_create(lead_id).get("facts") or {}
        self.assertIsNotNone(stored.get("budget"))
        self.assertIsNone(stored.get("scope"))

    def test_planner_respects_llm_facts_same_turn(self):
        """Facts the LLM extracted THIS turn must suppress the matching
        question in the SAME turn's plan (no re-asking what was just said)."""
        db = make_db(self.tmp / "h4.db")
        brain_store = self.brain
        extraction = json.dumps({"scope": "7 pages incl donation portal"})
        router = FakeRouter({"extraction": extraction})
        sales, crm, _mem = _build_agent(db, self.brain, router)
        model = ConversationModel(self.tmp, brain_store)
        lead_id = crm.create_lead(source_channel="whatsapp", contact_whatsapp="551100004")
        lead = crm.get_lead(lead_id)
        result = sales.process_message(
            lead, "أريد بناء موقع لجمعية اسمها يمن تعاون مع بوابة تبرع وصفحة متطوعين")
        mem = ConversationMemory(crm).get_or_create(lead_id)
        plan = model.plan(lead=lead, mem=mem, agent_result=result,
                          text="أريد بناء موقع لجمعية اسمها يمن تعاون",
                          language="ar", channel="whatsapp")
        self.assertEqual(plan["question"]["field"], "integrations")


if __name__ == "__main__":
    unittest.main()
