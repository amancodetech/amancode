"""P1 unlocks — T1 bands live, professional packs, follow-up seeding,
rolling relationship summary, cross-sell once, style adaptation, multi-intent.
"""

from __future__ import annotations
import json
import unittest

from amancore.business_brain.store import BrainStore
from amancore.conversation import ConversationModel
from amancore.conversation.pricing_flow import QuoteFlow  # noqa: parity surface
from tests.common import ROOT, TempDirTestCase, make_brain, make_db

ASSOC = "أريد بناء موقع لجمعية اسمها يمن تعاون"


class T1BandTests(TempDirTestCase, unittest.TestCase):
    """Real repo brain now carries owner-derived public bands."""

    def setUp(self):
        super().setUp()
        self.model = ConversationModel(ROOT, BrainStore(ROOT / "amancore" / "business_brain"))

    def test_t1_engages_in_commercial_brief(self):
        # D1-APPROVED gate: T1 needs category + shape + one other group.
        # Timeline alone is NOT scope context (must stay T0 — see
        # tests/unit/test_t1_groups.py); the seed stands in for prior
        # discovery of both shape and scale.
        plan = self.model.plan(lead={"lead_id": "L"},
                               mem={"facts": {"scope": "موقع جمعية",
                                              "timeline": "خلال شهرين"}},
                               agent_result={},
                               text="كم تستغرق مدة موقع جمعية؟",
                               language="ar", channel="whatsapp")
        self.assertEqual(plan["mode"], "COMMERCIAL")
        self.assertEqual(plan["commercial"]["tier"], "T1")
        brief = plan["brief"]
        self.assertIn("1500", brief)
        self.assertIn("4200", brief)
        # guard contract receives the band numbers
        self.assertIn("1500", plan["quality"]["allowed_numbers"])
        self.assertIn("4200", plan["quality"]["allowed_numbers"])

    def test_no_band_still_never_invents(self):
        model = ConversationModel(self.tmp, make_brain(self.tmp))
        # tmp brain is seeded from real v1 which NOW has bands — strip them
        # to prove the no-band degradation path still refuses to invent.
        _, data = model.brain_store.current()
        data.pop("price_bands_public", None)
        model.planner._brain = lambda: data
        plan = model.plan(lead={"lead_id": "L"}, mem={"facts": {}},
                          agent_result={}, text="كم سعر الموقع؟",
                          language="ar", channel="whatsapp")
        self.assertEqual(plan["commercial"]["tier"], "T0")
        self.assertNotIn("1500", plan["brief"])


class IndustryPacksTests(unittest.TestCase):
    def test_fourteen_professional_packs_complete(self):
        store = BrainStore(ROOT / "amancore" / "business_brain")
        _v, brain = store.current()
        profiles = brain["industry_profiles"]
        required = {"aliases", "goals", "typical_sections", "features",
                    "conversion", "trust_needs", "relevant_services",
                    "cross_sell", "resources_for_followup"}
        expected = {
            "association_ngo", "restaurant", "real_estate", "ecommerce",
            "clinic_healthcare", "construction", "education", "consulting",
            "law", "logistics", "manufacturing", "technology_startup",
            "professional_services", "generic_business",
        }
        self.assertEqual(set(profiles), expected)
        for key, pack in profiles.items():
            missing = [f for f in required
                       if f not in pack
                       and not (key == "generic_business" and f == "aliases")]
            self.assertFalse(missing, f"{key} missing {missing}")
        # live-proven association behavior must remain byte-stable
        self.assertEqual(
            profiles["association_ngo"]["typical_sections"],
            ["الرئيسية", "من نحن", "برامجنا", "كيف تتبرع",
             "احتياجات المستفيدين", "الأخبار", "تواصل معنا"])


class P1BehaviorTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)   # seeded from real v1 → has bands
        self.model = ConversationModel(self.tmp, self.brain)

    def _plan(self, text, wm=None, facts=None):
        return self.model.plan(lead={"lead_id": "L"}, mem={"facts": facts or {},
                                                          "working_memory": wm or {}},
                               agent_result={}, text=text, language="ar",
                               channel="whatsapp")

    def test_style_adaptation_short_customer(self):
        p = self._plan("موقع", {"mode": "NEED"})
        self.assertEqual(p["constraints"]["style"], "short")
        self.assertLessEqual(p["constraints"]["max_words"], 25)
        self.assertIn("very short", p["brief"])

    def test_style_adaptation_detailed_customer(self):
        long_msg = "نريد موقعاً متكاملاً للجمعية يشمل بوابة تبرع وتقارير دورية وصفحة متطوعين ومعرض صور للأنشطة وأرشيف أخبار ونموذج تواصل مباشر مع الفريق المسؤول عن كل برنامج من برامجنا الخيرية المتعددة"
        p = self._plan(long_msg)
        self.assertEqual(p["constraints"]["style"], "detailed")
        self.assertGreaterEqual(p["constraints"]["max_words"], 70)

    def test_multi_intent_queues_secondary_category(self):
        p = self._plan("أريد موقع ومتجر إلكتروني للمجموعة")
        self.assertEqual(p["service_category"], "website")
        self.assertIn("متجر", p["brief"])          # acknowledged, deferred
        wm = p["working_memory"]
        self.assertEqual(wm["intent_queue"], ["ecommerce"])

    def test_intent_queue_resumes_next_turn(self):
        wm = {"mode": "SHAPING", "industry": "association_ngo",
              "intent_queue": ["ecommerce"]}
        p = self._plan("تمام تابع", wm)
        self.assertEqual(p["service_category"], "ecommerce")
        self.assertTrue(p["brief"].startswith("Continuing"))
        self.assertEqual(p["working_memory"]["intent_queue"], [])

    def test_crosssell_mentioned_once_only(self):
        p1 = self._plan(ASSOC)
        wm = p1["working_memory"]
        wm.update({"mode": "SHAPING", "structure_proposed": False})
        p2 = self._plan("نعم تمام", wm)
        self.assertIn("whatsapp integration", p2["brief"])
        self.assertTrue(p2["working_memory"].get("crosssell_done"))
        wm2 = dict(p2["working_memory"])
        wm2["mode"] = "COMMERCIAL"
        p3 = self._plan("كم تستغرقون؟", wm2)
        self.assertNotIn("whatsapp integration", p3["brief"])

    def test_opening_uses_relationship_summary(self):
        p = self._plan("مرحبا", {})
        # no summary yet -> plain opening
        self.assertNotIn("Relationship memory", p["brief"])
        mem = {"facts": {}, "summary": "النشاط: association_ngo؛ scope: بوابة تبرع"}
        p2 = self.model.plan(lead={"lead_id": "L", "consent_at": "2026-01-01"},
                             mem=mem, agent_result={}, text="مرحبا",
                             language="ar", channel="whatsapp")
        self.assertIn("Relationship memory", p2["brief"])
        self.assertIn("بوابة تبرع", p2["brief"])


class FollowupSeedTests(TempDirTestCase, unittest.TestCase):
    """Coordinator seeds next_followup_at on hesitation/indecision/recommendation."""

    WA = "905000000777"

    def _build(self):
        from amancore.agents.sales import SalesAgent
        from amancore.channels.coordinator import MessageCoordinator
        from amancore.channels.handover import HandoverService
        from amancore.channels.language import LanguageDetector
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from amancore.channels.response_filter import ExternalResponseFilter
        from amancore.channels.whatsapp import WhatsAppAdapter
        from amancore.crm.service import CRMService
        from amancore.ops.cost_governor import CostGovernor
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

        db = make_db(self.tmp / "fu.db")
        brain = self.brain if hasattr(self, "brain") else make_brain(self.tmp)
        audit = AuditService(db)
        dispatcher = EventDispatcher()
        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(db)
        chpolicy = ChannelPolicyEngine(brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=audit, dispatcher=dispatcher)
        crm = CRMService(db)
        memory = ConversationMemory(crm)
        sales = SalesAgent(brain, crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(brain),
                           FollowupEngine(), HandoffService(dispatcher),
                           audit=audit, dispatcher=dispatcher)
        coord = MessageCoordinator(
            {"whatsapp": adapter}, outbox, worker, sales, crm, memory,
            HandoverService(crm, dispatcher), ExternalResponseFilter(),
            chpolicy, IdempotencyStore(db), LanguageDetector(),
            LocalizationSkill(), PricingSnapshotStore(db), ProposalStore(db),
            owner_alert=lambda *a, **k: None, audit=audit,
            dispatcher=dispatcher, cost_governor=CostGovernor({}),
            conversation=ConversationModel(self.tmp, brain))
        cap = _Cap() if "_Cap" in globals() else None
        class _C:
            def __init__(s):
                s.messages = []
            def complete(s, messages):
                s.messages.append(messages)

                class _O:
                    text = "تم"
                return _O()
        cap = _C()
        coord._drafter = cap
        return coord, cap, db

    @staticmethod
    def _body(text, mid, wa):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"wa_id": wa}],
                    "messages": [{"from": wa, "id": mid, "type": "text",
                                  "text": {"body": text}}]}}]}]}

    def test_seeded_on_hesitation(self):
        from datetime import datetime

        coord, _cap, db = self._build()
        wa = self.WA
        coord.handle_inbound("whatsapp", self._body(ASSOC, "f1", wa))
        lead_id = db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (wa,)).fetchone()["lead_id"]
        before = db.execute(
            "SELECT next_followup_at FROM leads WHERE lead_id=?",
            (lead_id,)).fetchone()["next_followup_at"]
        self.assertIsNone(before)
        summary = coord.handle_inbound(
            "whatsapp", self._body("حسناً سأفكر في الأمر وأرد عليك لاحقاً", "f2", wa))
        row = db.execute(
            "SELECT next_followup_at FROM leads WHERE lead_id=?",
            (lead_id,)).fetchone()["next_followup_at"]
        self.assertIsNotNone(row, "hesitation must seed a follow-up")
        parsed = datetime.fromisoformat(row)
        delta_days = abs((parsed - datetime.now(parsed.tzinfo)).days)
        self.assertLessEqual(delta_days, 3)


if __name__ == "__main__":
    unittest.main()


class SuggestIntakeTests(TempDirTestCase, unittest.TestCase):
    """«اقترح لي» → أسئلة سهلة بخيارات أولاً، ثم اقتراح كامل مبني عليها."""

    def setUp(self):
        super().setUp()
        self.model = ConversationModel(self.tmp, make_brain(self.tmp))

    def _plan(self, text, wm=None):
        return self.model.plan(lead={"lead_id": "L"}, mem={"facts": {},
                                                          "working_memory": wm or {}},
                               agent_result={}, text=text, language="ar",
                               channel="whatsapp")

    def _to_shaping(self, text="أريد موقع لجمعية"):
        p = self._plan(text)
        return p["working_memory"]

    def test_intake_asks_first_choice_question(self):
        wm = self._to_shaping()
        p = self._plan("لا أدري، اقترح لي", wm)
        self.assertTrue(p["question_is_choice"])
        self.assertIn("Options:", p["brief"])
        self.assertIn("بوابة تبرع إلكترونية", p["brief"])
        self.assertNotIn("FULL concrete structure", p["brief"])
        self.assertEqual(p["question"]["field"], "suggest_donation")

    def test_second_clarifier_then_full_proposal(self):
        wm = self._to_shaping()
        p1 = self._plan("اقترح لي", wm)
        wm1 = p1["working_memory"]
        p2 = self._plan("بوابة تبرع إلكترونية", wm1)
        self.assertIn("بأي لغة", p2["brief"])            # second clarifier
        p3 = self._plan("عربي وإنجليزي", p2["working_memory"])
        self.assertIn("FULL concrete structure", p3["brief"])
        self.assertIn("بوابة تبرع إلكترونية", p3["brief"].split(
            "Base it on their choices:")[-1])
        self.assertNotIn("suggestion_active",
                         json.dumps(p3["working_memory"]))

    def test_skip_jumps_to_proposal_with_defaults(self):
        wm = self._to_shaping()
        p = self._plan("اقترح مباشرة بدون أسئلة", wm)
        self.assertIn("FULL concrete structure", p["brief"])
        self.assertIn("default assumptions", p["brief"])


class MiniBandTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)
        self.model = ConversationModel(self.tmp, self.brain)

    def test_small_scope_picks_mini_band(self):
        # D1-APPROVED gate: the mini band needs shape + one other group
        # (seeded here as prior discovery would provide them).
        p = self.model.plan(lead={"lead_id": "L"},
                            mem={"facts": {"scope": "موقع تعريفي",
                                           "timeline": "قريب"},
                                 "working_memory":
                                 {"mode": "SHAPING", "service_category": "website"}},
                            agent_result={},
                            text="موقع تعريفي من صفحتين، كم تستغرقون؟",
                            language="ar", channel="whatsapp")
        self.assertEqual(p["commercial"]["tier"], "T1")
        self.assertEqual(p["commercial"]["low"], 450)
        self.assertEqual(p["commercial"]["high"], 1200)
        self.assertIn("450", plan_brief := p["brief"])

    def test_estimate_hours_override_for_small_sites(self):
        from amancore.conversation.pricing_flow import QuoteFlow
        from amancore.crm.service import CRMService
        from amancore.pricing.snapshot import PricingSnapshotStore
        db = make_db(self.tmp / "mini.db")
        crm = CRMService(db)
        flow = QuoteFlow(db, crm, self.brain,
                         PricingSnapshotStore(db))
        est_small = flow.estimate({"language": "ar"}, "website", hours_override=6)
        est_std = flow.estimate({"language": "ar"}, "website")
        self.assertLess(est_small["high"], est_std["low"])   # منطقي: المصغّر أقل من أرضي المعياري
        self.assertEqual(est_small["high"], 1200)
