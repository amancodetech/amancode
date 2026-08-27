"""P0-1 Conversation Operating Model tests.

Pins the new single-source steering chain:
    Context -> Policy -> ModeManager -> ResponsePlanner -> LLM (HOW only)
and guards the legacy path regression hatch (conversation=None).
"""

from __future__ import annotations

import unittest

from amancore.business_brain.store import BrainStore
from amancore.business_brain.validator import validate_brain
from amancore.conversation import ConversationModel
from amancore.conversation.modes import ModeManager
from amancore.conversation.policy import ConversationPolicy
from tests.common import ROOT, TempDirTestCase, make_brain, make_db

ASSOCIATION_MSG = "أريد بناء موقع لجمعية اسمها يمن تعاون"


class _Out:
    def __init__(self, text="حسناً"):
        self.text = text


class CaptureDrafter:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return _Out("تم")


def fresh_policy():
    return ConversationPolicy()  # code defaults, no yaml


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = fresh_policy()

    def test_service_category_detection_ar_en(self):
        self.assertEqual(self.p.detect_service_category("أريد بناء موقع"), "website")
        self.assertEqual(self.p.detect_service_category("I need a mobile app"), "mobile")
        self.assertEqual(self.p.detect_service_category("احتاج ERP للمخزون"), "business_system")

    def test_industry_aliases(self):
        self.assertEqual(self.p.detect_industry(ASSOCIATION_MSG), "association_ngo")
        self.assertEqual(self.p.detect_industry("موقع لمطعم شاورما"), "restaurant")
        self.assertIsNone(self.p.detect_industry("hello"))

    def test_budget_gated_outside_commercial(self):
        w_need = self.p.weights_for("website", "NEED")
        self.assertEqual(w_need["budget_band"], 0)
        w_comm = self.p.weights_for("website", "COMMERCIAL")
        self.assertGreaterEqual(w_comm["budget_band"], 9)

    def test_single_high_value_question_website(self):
        ask = self.p.next_question("website", "NEED", facts={})
        self.assertIsNotNone(ask)
        self.assertEqual(ask[0], "key_features")

    def test_no_question_when_all_known(self):
        facts = {"scope": "x", "users": "y", "languages": "ar", "integrations": "wa",
                 "timeline": "soon", "authority": "owner", "budget": "$5k"}
        self.assertIsNone(self.p.next_question("website", "COMMERCIAL", facts))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.mm = ModeManager(fresh_policy())

    def test_greeting_is_opening_request_is_need(self):
        self.assertEqual(self.mm.initial_mode("مرحبا", None), "OPENING")
        self.assertEqual(self.mm.initial_mode(ASSOCIATION_MSG, "website"), "NEED")

    def test_structure_proposed_advances_to_shaping(self):
        mode, wm = self.mm.advance("NEED", text="نعم تمام",
                                   agent_result={},
                                   working_memory={"structure_proposed": True})
        self.assertEqual(mode, "SHAPING")
        self.assertFalse(wm["structure_proposed"])

    def test_commercial_signal_jumps_from_shaping(self):
        mode, _ = self.mm.advance("SHAPING", text="كم تستغرق المدة عادة؟",
                                  agent_result={}, working_memory={})
        self.assertEqual(mode, "COMMERCIAL")

    def test_objection_in_commercial_becomes_negotiation(self):
        mode, wm = self.mm.advance("COMMERCIAL", text="السعر غالي",
                                   agent_result={"objection": "price_high"},
                                   working_memory={})
        self.assertEqual(mode, "NEGOTIATION")
        self.assertEqual(wm.get("return_mode"), "COMMERCIAL")


class PlannerTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)
        self.model = ConversationModel(self.tmp, self.brain)
        self.lead = {"lead_id": "L1", "industry": None}

    def _plan(self, text, mem=None, agent_result=None):
        return self.model.plan(lead=dict(self.lead), mem=mem or {"facts": {}},
                               agent_result=agent_result or {}, text=text,
                               language="ar", channel="whatsapp")

    def test_association_value_first_plan(self):
        plan = self._plan(ASSOCIATION_MSG)
        self.assertEqual(plan["mode"], "NEED")
        self.assertEqual(plan["industry"], "association_ngo")
        self.assertIn("كيف تتبرع", " | ".join(plan["value_payload"].get("sections", [])))
        self.assertEqual(plan["question"]["field"], "key_features")
        # value-first guarantees: no legacy challenge-template, no prices
        self.assertNotIn("challenge with how you currently", plan["brief"].lower())
        self.assertNotIn("أكبر التحديات", plan["brief"])
        self.assertIsNone(plan["commercial"]["price_figure"])
        self.assertTrue(plan["working_memory"]["structure_proposed"])

    def test_second_turn_shapes_with_named_service(self):
        p1 = self._plan(ASSOCIATION_MSG)
        mem2 = {"facts": {}, "working_memory": p1["working_memory"]}
        p2 = self._plan("نعم لكن نريد صفحة متطوعين", mem=mem2)
        self.assertEqual(p2["mode"], "SHAPING")
        self.assertIn("Business Website System", p2["brief"])

    def test_commercial_mode_never_injects_numbers_without_bands(self):
        # Owner-approved bands NOW exist in the live Brain (T1 unlocked);
        # strip them here to pin the degradation contract: without bands
        # the planner must never invent a single figure.
        import copy

        plan = self._plan("اريد موقع، كم تستغرق المدة؟",
                          mem={"facts": {}, "working_memory":
                               {"mode": "SHAPING", "service_category": "website"}})
        self.assertEqual(plan["mode"], "COMMERCIAL")
        stripped = copy.deepcopy(self.model.planner._brain())
        stripped.pop("price_bands_public", None)
        self.model.planner._brain = lambda s=stripped: s
        try:
            plan0 = self._plan("اريد موقع، كم تستغرق المدة؟",
                               mem={"facts": {}, "working_memory":
                                    {"mode": "SHAPING",
                                     "service_category": "website"}})
        finally:
            del self.model.planner._brain
        self.assertEqual(plan0["commercial"]["tier"], "T0")
        self.assertNotIn("1500", plan0["brief"])
        self.assertIsNone(plan0["commercial"].get("band"))

    def test_recommendation_wrap_names_offer_only(self):
        rec = {"offer_name": "Business Website System", "service_name": "Business Website System",
               "message": "Based on what you've shared..."}
        plan = self._plan("ok", agent_result={"recommendation": rec},
                          mem={"facts": {}, "working_memory": {"mode": "SHAPING"}})
        self.assertEqual(plan["mode"], "COMMERCIAL")
        self.assertIn("Business Website System", plan["brief"])
        self.assertEqual(plan["base"], rec["message"])

    def test_working_memory_roundtrip_through_memory_layer(self):
        from amancore.crm.service import CRMService
        from amancore.sales.conversation_memory import ConversationMemory

        db = make_db(self.tmp / "p01.db")
        crm = CRMService(db)
        memory = ConversationMemory(crm)
        lead_id = crm.create_lead(source_channel="whatsapp", contact_whatsapp="551199999")
        plan = self._plan(ASSOCIATION_MSG)
        self.model.persist(memory, lead_id, channel="whatsapp",
                           language="ar", working_memory=plan["working_memory"])
        restored = memory.get_or_create(lead_id, channel="whatsapp", language="ar")
        self.assertEqual(restored["working_memory"].get("mode"), "NEED")
        self.assertEqual(restored["working_memory"].get("industry"), "association_ngo")


class CoordinatorIntegrationTests(TempDirTestCase, unittest.TestCase):
    """End-to-end through handle_inbound with a captured drafter."""

    def _build(self, with_conversation=True):
        import inspect

        from amancore.agents.sales import SalesAgent
        from amancore.channels.coordinator import MessageCoordinator
        from amancore.channels.handover import HandoverService
        from amancore.channels.language import LanguageDetector
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from amancore.channels.response_filter import ExternalResponseFilter
        from amancore.channels.whatsapp import WhatsAppAdapter
        from amancore.crm.service import CRMService
        from amancore.pricing.proposal import ProposalStore
        from amancore.pricing.snapshot import PricingSnapshotStore
        from amancore.sales.conversation_memory import ConversationMemory
        from amancore.sales.discovery import DiscoveryEngine
        from amancore.sales.followup import FollowupEngine
        from amancore.sales.handoff import HandoffService
        from amancore.sales.qualification import QualificationEngine
        from amancore.services.audit import AuditService
        from amancore.services.events import EventDispatcher, IdempotencyStore
        from amancore.skills.localization import LocalizationSkill
        from amancore.skills.objection_handling import ObjectionHandlingSkill

        db = make_db(self.tmp / f"c{int(with_conversation)}.db")
        brain = make_brain(self.tmp)
        audit = AuditService(db)
        dispatcher = EventDispatcher()
        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(db)
        policy = ChannelPolicyEngine(brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, policy,
                              audit=audit, dispatcher=dispatcher)
        memory = ConversationMemory(CRMService(db))
        crm = CRMService(db)
        sales = SalesAgent(brain, crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(brain),
                           FollowupEngine(), HandoffService(dispatcher),
                           audit=audit, dispatcher=dispatcher)
        kwargs = {}
        if with_conversation:
            kwargs["conversation"] = ConversationModel(self.tmp, brain)
        coord = MessageCoordinator(
            adapter, outbox, worker, sales, crm, memory,
            HandoverService(crm, dispatcher), ExternalResponseFilter(), policy,
            IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(db), ProposalStore(db),
            owner_alert=lambda *a, **k: None,
            audit=audit, dispatcher=dispatcher, **kwargs)
        drafter = CaptureDrafter()
        coord._drafter = drafter
        return coord, drafter, db

    @staticmethod
    def _body(text, msg_id):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"wa_id": "551199999", "profile": {"name": "A"}}],
                    "messages": [{"from": "551199999", "id": msg_id, "type": "text",
                                  "text": {"body": text}}]}}]}]}

    def test_new_path_value_first_no_challenge_question(self):
        coord, drafter, db = self._build(with_conversation=True)
        coord.handle_inbound("whatsapp", self._body("مرحبا", "m1"))
        self.assertIn("MODE=OPENING", str(drafter.messages[0]))
        drafter.messages.clear()
        summary = coord.handle_inbound("whatsapp", self._body(ASSOCIATION_MSG, "m2"))
        self.assertEqual(summary["replies"], 1)
        prompt = str(drafter.messages[0])
        self.assertIn("كيف تتبرع", prompt)          # industry value payload
        self.assertIn("ONE high-value question", prompt)
        self.assertNotIn("DISCOVERY PLAYBOOK", prompt)   # dual authority is dead
        self.assertNotIn("challenge with how you currently", prompt.lower())
        row = db.execute(
            "SELECT working_memory FROM conversations").fetchone()
        self.assertIsNotNone(row["working_memory"])
        self.assertIn('"mode"', row["working_memory"])

    def test_legacy_path_untouched_without_model(self):
        """Regression hatch: conversation=None keeps the exact legacy turn
        shape (discovery template rides as DRAFT CONTENT, generic purpose).
        (Documents reality: the agent never emitted next_action, so the old
        playbook branch was already unreachable — the template rode in base.)"""
        coord, drafter, _db = self._build(with_conversation=False)
        coord.handle_inbound("whatsapp", self._body(ASSOCIATION_MSG, "m1"))
        prompt = str(drafter.messages[0])
        self.assertIn("Purpose: sales conversation", prompt)
        self.assertIn("DRAFT CONTENT: What would a successful outcome",
                      prompt)


class BrainAdditionsTests(TempDirTestCase, unittest.TestCase):
    def test_repo_brain_validates_with_new_sections(self):
        store = BrainStore(ROOT / "amancore" / "business_brain")
        _version, data = store.current()
        self.assertEqual(validate_brain(data), [])
        profiles = data.get("industry_profiles") or {}
        for key in ("association_ngo", "restaurant", "real_estate", "ecommerce",
                    "generic_business"):
            self.assertIn(key, profiles)
        service_ids = {s["id"] for s in data["services"]}
        self.assertIn("ecommerce_store", service_ids)
        self.assertIn("ai_automation_suite", service_ids)

    def test_policy_yaml_loads_and_overrides_apply(self):
        policy = ConversationPolicy.load(ROOT)
        self.assertTrue(policy.value_first_enabled)
        self.assertEqual(policy.max_questions, 1)
        # shipped yaml mirrors defaults; shallow-merge must not lose keys
        self.assertIn("automation", policy.data["service_categories"])


if __name__ == "__main__":
    unittest.main()
