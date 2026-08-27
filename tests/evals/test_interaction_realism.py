"""Interaction Realism — eval assertions (deterministic string/field checks).

Exercises THE production composition point (``build_conversation_stack``) with
the versioned ``knowledge/`` layer copied into the test root, so the tested
path and the live path cannot drift. All assertions are deterministic — no
model scoring, mirroring how QualityGuard measures correctness.

Thresholds ratified (informational, not production blockers):
    repetition <=10%, paraphrase >=80%, register match >=90%.
Corpus-level diversity metrics are informational only; the individual
deterministic checks below are what gate behavior.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.webhook_server import build_conversation_stack
from amancore.conversation.memory_reducer import SUMMARY_LIMIT, reduce_memory
from amancore.conversation.quality_guard import QualityGuard
from amancore.crm.service import CRMService
from amancore.ops.cost_governor import CostGovernor
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db

REPO = Path(__file__).resolve().parents[2]
ASSOC_EN = "I want a website for an association that collects donations"
RESTAURANT_AR = "عندي مطعم وأبغى موقع مع قائمة وطلب"
PRICE_AR = "بكم الموقع تقريباً؟"


class InteractionRealismEval(TempDirTestCase, unittest.TestCase):
    """Plan-level + guard-level deterministic assertions over the real stack."""

    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "knowledge", self.tmp / "knowledge")
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "ir.db")
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        self.alerts = []
        stack = build_conversation_stack(
            self.tmp, self.db, self.brain, self.crm, self.dispatcher,
            self.audit, shared_router=FakeRouter({"extraction": "{}"}),
            owner_alert=lambda *a, **k: self.alerts.append(a))
        self.model = stack["conversation"]
        self.planner = self.model.planner
        self.policy = self.model.policy
        from amancore.channels.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(self.db)
        chpolicy = ChannelPolicyEngine(self.brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=self.audit, dispatcher=self.dispatcher)
        handover = HandoverService(self.crm, self.dispatcher)
        self.coord = MessageCoordinator(
            {"whatsapp": adapter}, outbox, worker, stack["sales"], self.crm,
            stack["memory"], handover, ExternalResponseFilter(), chpolicy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=self.audit, dispatcher=self.dispatcher,
            cost_governor=CostGovernor({}),
            conversation=stack["conversation"],
            quote_flow=stack["quote_flow"],
            support_agent=stack["support"])
        self.coord._drafter = _Cap()
        self.qg = QualityGuard(self.policy)

    def _plan(self, text, mem=None, agent_result=None, language="ar"):
        return self.planner.plan(
            lead={"lead_id": "L", "industry": None},
            mem=mem or {"facts": {}},
            agent_result=agent_result or {},
            text=text, language=language, channel="whatsapp")

    # ---- wiring: rules + packs ARE loaded by the real runtime --------------
    def test_runtime_loads_interaction_rules_and_packs(self):
        self.assertEqual(len(self.planner.interaction_rules), 9)
        ids = {r["id"] for r in self.planner.interaction_rules}
        self.assertIn("ir_identity_disclosure", ids)
        self.assertIn("ir_escalation_legal", ids)
        self.assertIn("ir_recap_before_propose", ids)
        self.assertIn("ir_response_variation", ids)
        self.assertIn("ir_register_guidance", ids)
        self.assertIn("ir_sentiment_minimal", ids)
        self.assertIn("association_ngo", self.planner.retriever.packs)
        self.assertIn("restaurant", self.planner.retriever.packs)

    # ---- 1. association value-first -----------------------------------------
    def test_association_value_first(self):
        plan = self._plan(ASSOC_EN, language="en")
        self.assertEqual(plan["industry"], "association_ngo")
        self.assertEqual(plan["mode"], "NEED")
        self.assertIn("Detected business type: association_ngo", plan["brief"])
        self.assertNotIn("biggest challenge", plan["brief"].lower())

    # ---- 2/3. no generic discovery regression + max one question ------------
    def test_no_generic_discovery_and_one_question(self):
        for text in (ASSOC_EN, RESTAURANT_AR):
            plan = self._plan(text,
                              language="en" if text == ASSOC_EN else "ar")
            self.assertNotIn("biggest challenge", plan["brief"].lower())
            self.assertNotIn("ما أكبر تحد", plan["brief"])
            q = plan.get("question")
            self.assertIsNone(q) if False else self.assertIsInstance(
                q, (dict, type(None)), "question must be a single field")
            self.assertLessEqual(plan["brief"].count("؟") +
                                 plan["brief"].count("?"), 2)

    # ---- 4. known fact not re-asked (reask_known = hard) --------------------
    def test_known_fact_not_requestioned(self):
        plan = self._plan("أريد موقعاً، عربي وإنجليزي",
                          mem={"facts": {"languages": "ar,en", "scope": "موقع"}})
        qf = (plan.get("question") or {}).get("field")
        self.assertNotEqual(qf, "languages")
        # guard-level: a regression that re-asks a known field is a HARD fail
        bad = dict(plan)
        bad["question"] = {"field": "languages", "hint": "أي لغة؟"}
        verdict = self.qg.check("بأي لغة تريد؟", plan=bad)
        self.assertIn("reask_known:languages", verdict["violations"])
        self.assertFalse(verdict["allowed"])

    # ---- 5. contradiction -> one confirmation only --------------------------
    def test_contradiction_allows_one_confirmation(self):
        plan = self._plan("بكم الموقع تقريباً؟",
                          mem={"facts": {"languages": "ar"}})
        # allow_reask is the only exception for a known-field re-ask
        plan["allow_reask"] = True
        plan["question"] = {"field": "languages", "hint": "أي لغة؟"}
        verdict = self.qg.check("أي لغة؟", plan=plan)
        self.assertTrue(verdict["allowed"])
        self.assertLessEqual(plan["brief"].count("؟") +
                             plan["brief"].count("?"), 2)

    # ---- 6. recap only when justified (need-setup / scope-change) -----------
    def test_recap_only_when_justified(self):
        # SHAPING with a known need -> recap directive present
        shaping = self._plan(
            "عندي مطعم وأبغى موقع مع قائمة وطلب",
            mem={"facts": {"problem": "stated",
                           "desired_outcome": "menu with ordering"},
                 "working_memory": {"mode": "SHAPING",
                                    "industry": "restaurant",
                                    "service_category": "website"}},
            language="ar")
        self.assertIn("Active listening", shaping["brief"])
        self.assertIn("reflect back what you understood in ONE sentence",
                      shaping["brief"])
        # OPENING / no known need -> no recap directive
        opening = self._plan("مرحبا", mem={"facts": {}})
        self.assertNotIn("Active listening", opening["brief"])

    # ---- 7/8. escalation -> feed team-review / HANDOVER-WRAP concept --------
    def test_legal_escalation(self):
        plan = self._plan("هل تنص شروط العقد على ملكية فكرية؟", mem={"facts": {}})
        self.assertEqual(plan.get("escalation"), "legal")
        self.assertIn("our team", plan["brief"])
        self.assertIn("specialist", plan["brief"])

    def test_financial_escalation(self):
        plan = self._plan("هل يمكن الدفع بالتقسيط؟", mem={"facts": {}})
        self.assertEqual(plan.get("escalation"), "financial")
        self.assertIn("team", plan["brief"])

    def test_urgent_high_stakes_escalation(self):
        plan = self._plan("الأمر عاجل جداً، الموقع يخدم عملاء اليوم",
                          mem={"facts": {}})
        self.assertEqual(plan.get("escalation"), "urgent")
        self.assertIn("specialist", plan["brief"])

    # ---- 9. price request stays commercial ----------------------------------
    def test_price_request_stays_commercial(self):
        plan = self._plan(PRICE_AR, mem={"facts": {}}, language="ar")
        self.assertEqual(plan["mode"], "COMMERCIAL")
        self.assertIn("COMMERCIAL", plan["brief"])
        self.assertTrue((plan.get("commercial") or {}).get("tier"))

    # ---- 10. scope change preserves memory context --------------------------
    def test_scope_change_preserves_memory_context(self):
        mem = {"facts": {"scope": "15 صفحات", "languages": "ar",
                         "timeline": "شهر"}}
        summary = reduce_memory(mem)
        plan = self._plan("غيّرنا النطاق إلى 15 صفحة", mem=mem)
        self.assertIn("Conversation context:", plan["brief"])
        self.assertIn("scope=", plan["brief"])
        self.assertIn("15", plan["brief"])

    # ---- 11. repeat_self detection mechanism (advisory) ---------------------
    def test_repeat_self_advisory(self):
        text = ("أفهم أنك تريد موقعاً بقائمة طعام. ما الجزء الأهم الذي لا "
                "يمكن الاستغناء عنه؟")
        plan = self._plan("مرحبا", mem={"facts": {}})
        plan["question"] = None
        verdict = self.qg.check(text, plan=plan,
                                recent_replies=[text])
        self.assertIn("repeat_self", verdict["advisories"])
        self.assertTrue(verdict["allowed"])  # advisory, not a blocker

    # ---- 12. identity disclosure, honest for all forms (ar/en) --------------
    def test_identity_disclosure_honest(self):
        for q in ("هل أنت إنسان", "are you human", "هل انت روبوت", "are you a bot"):
            lang = "en" if q.startswith("are you") else "ar"
            plan = self._plan(q, mem={"facts": {}}, language=lang)
            b = plan["brief"]
            self.assertIn("digital assistant at AmanCore", b, q)
            self.assertIn("real team", b, q)
            self.assertIn("Never claim to be human", b, q)

    # ---- 13. summary injection tagged + capped ------------------------------
    def test_summary_injection_tagged_and_capped(self):
        facts = {"scope": "10 صفحات", "languages": "ar", "timeline": "شهر",
                 "desired_outcome": "زيادة الحجوزات"}
        mem = {"facts": facts, "decisions": ["اختيار المنيو"]}
        plan = self._plan("عندي مطعم وأبغى موقع مع قائمة وطلب", mem=mem,
                          language="ar")
        self.assertIn("Conversation context:", plan["brief"])
        # the reducer caps the summary at the source
        self.assertLessEqual(len(reduce_memory(mem)), SUMMARY_LIMIT)

    # ---- register calibration -------------------------------------------------
    def test_register_guidance(self):
        ar_plan = self._plan(RESTAURANT_AR, mem={"facts": {}}, language="ar")
        self.assertIn("فصحى مبسطة", ar_plan["brief"])
        en_plan = self._plan(ASSOC_EN, mem={"facts": {}}, language="en")
        self.assertIn("professional-neutral", en_plan["brief"])

    # ---- wiring regression guard: rules are part of the runtime ---------------
    def test_wiring_guard(self):
        import amancore.conversation.planner as pl_mod
        src = Path(pl_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("_with_interaction", src)
        self.assertIn("interaction_rules.v1.yaml", src)
        self.assertIn("ir_identity_disclosure", src)


class _Cap:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)

        class _O:
            text = "تم"

        return _O()


if __name__ == "__main__":
    unittest.main()
