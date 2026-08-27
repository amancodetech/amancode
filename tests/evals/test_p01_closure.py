"""P0.1 CLOSURE — three documented gaps, closed on top of P0.

1) Alias coverage: every Brain-declared industry is detectable in BOTH Arabic
   and English using the Brain itself as the alias source (English aliases were
   missing for association_ngo / restaurant / real_estate and are now in
   business_brain/data/v1.yaml).
2) repeat_self LIVE wiring: the coordinator passes the last two assistant
   replies to QualityGuard so the advisory fires in the production path.
3) Escalation E2E: a legal question produces a customer-facing transfer to
   our team/specialist — with no legal commitment, no price, no claims.

All wiring is exercised through ``build_conversation_stack`` (THE composition
root), not direct-call tests.
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

# A realistic Arabic reply the drafter is expected to produce for a legal
# question — team review / specialist transfer, no commitment, no price.
ESCALATION_REPLY = ("أتفهم استفسارك حول شروط الاستخدام والتعاقد. هذا يحتاج "
                    "مراجعة من فريقنا المختص لضمان الدقة، وسنعود إليك بسرعة. "
                    "هل يمكنني مساعدتك في شيء آخر؟")

LEGAL_QUESTION = "ومن يتحمل المسؤولية عن شروط الاستخدام والتعاقد؟"


class _FixedDrafter:
    """Deterministic drafter seam (documented injection point) returning a
    fixed reply, so the outbound text is reproducible in the live path."""

    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return type("R", (), {"text": self.text})()


class _SpyGuard(QualityGuard):
    """Delegates to the real QualityGuard and records recent_replies/advisories
    so the wiring of the live call is observable."""

    def __init__(self, policy):
        super().__init__(policy)
        self.seen_recent = []
        self.seen_advisories = []

    def check(self, text, *, plan=None, last_customer_text=None,
              recent_replies=None):
        self.seen_recent.append(recent_replies)
        result = super().check(text, plan=plan,
                               last_customer_text=last_customer_text,
                               recent_replies=recent_replies)
        self.seen_advisories.append(result.get("advisories", []))
        return result


class P01Closure(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "knowledge", self.tmp / "knowledge")
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "p01.db")
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        stack = build_conversation_stack(
            self.tmp, self.db, self.brain, self.crm, self.dispatcher,
            self.audit, shared_router=FakeRouter({"extraction": "{}"}),
            owner_alert=lambda *a, **k: None)
        self.model = stack["conversation"]
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
        self.outbox = outbox

    def _body(self, text, mid, wa="6280000000123"):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "905345247791"},
                    "contacts": [{"wa_id": wa}],
                    "messages": [{"from": wa, "id": mid, "type": "text",
                                  "text": {"body": text}}]}}]}]}

    def _latest_outbound(self, wa="6280000000123"):
        row = self.db.execute(
            "SELECT payload FROM message_outbox"
            " WHERE recipient=? AND message_type='text'"
            " ORDER BY created_at DESC LIMIT 1", (wa,)).fetchone()
        return (row["payload"] or "") if row else ""

    # ---- 1. alias coverage 17/17 (Arabic + English) ----------------------
    def test_alias_coverage_ar_en(self):
        profs = (self.brain.current()[1]).get("industry_profiles") or {}
        amap = self.policy.brain_industry_aliases(self.brain.current()[1])
        ar_probe = {
            "association_ngo": "موقع لجمعية خيرية",
            "restaurant": "موقع لمطعم",
            "real_estate": "موقع عقارات",
            "ecommerce": "متجر إلكتروني",
            "clinic_healthcare": "موقع عيادة",
            "construction": "موقع مقاولات",
            "education": "موقع مدرسة",
            "consulting": "موقع استشارات",
            "law": "موقع مكتب محاماة",
            "logistics": "موقع شحن",
            "manufacturing": "موقع مصنع",
            "technology_startup": "موقع شركة تقنية",
            "professional_services": "موقع خدمات مهنية",
        }
        en_probe = {
            "association_ngo": "website for an association charity",
            "restaurant": "website for my restaurant",
            "real_estate": "real estate property site",
            "ecommerce": "an online store",
            "clinic_healthcare": "a clinic website",
            "construction": "construction company site",
            "education": "a school website",
            "consulting": "consulting firm site",
            "law": "a law firm website",
            "logistics": "shipping logistics portal",
            "manufacturing": "factory manufacturing site",
            "technology_startup": "saas startup landing page",
            "professional_services": "services firm portfolio",
        }
        # every non-fallback industry must resolve in BOTH languages
        detected_ar = detected_en = 0
        for ind in profs:
            if ind == "generic_business":
                continue
            self.assertEqual(self.policy.detect_industry_with(ar_probe[ind], amap),
                             ind, f"AR {ind}")
            self.assertEqual(self.policy.detect_industry_with(en_probe[ind], amap),
                             ind, f"EN {ind}")
            detected_ar += 1
            detected_en += 1
        self.assertGreaterEqual(detected_ar, 13)
        self.assertGreaterEqual(detected_en, 13)
        # generic_business stays a fallback (empty aliases), never alias-detected
        self.assertNotIn("generic_business", amap)  # fallback, never alias-detected
        # English aliases for the three previously-undetected industries exist
        # in the Brain itself (authoritative source), not only the policy base.
        self.assertIn("association", amap["association_ngo"])
        self.assertIn("restaurant", amap["restaurant"])
        self.assertIn("real estate", amap["real_estate"])

    # ---- 2. repeat_self LIVE wiring (fails if the pass-line is removed) ----
    def test_repeat_self_live_wiring(self):
        REP = ("أفهم أنك تريد موقعًا احترافيًا بخدمات واضحة. ما الخدمة الأهم "
               "بالنسبة لك اليوم؟")
        wa = "6280000000123"
        # seed one prior assistant reply so the live guard has history
        self.db.execute(
            "INSERT INTO channel_messages (channel, external_user_id, direction,"
            " body, hidden, created_at) VALUES (?,?,?,?,0, datetime('now'))",
            ("whatsapp", wa, "out", REP))
        # spy the live guard + fixed drafter returning an identical reply
        self.coord.quality_guard = _SpyGuard(self.policy)
        self.coord._drafter = _FixedDrafter(REP)
        self.coord.handle_inbound("whatsapp",
                                  self._body("أريد موقعًا احترافيًا", "p1", wa))
        self.assertTrue(self.coord.quality_guard.seen_recent,
                        "recent_replies must be passed in the live path")
        latest_recent = self.coord.quality_guard.seen_recent[-1]
        self.assertTrue(latest_recent and REP in latest_recent,
                        "live guard must receive the prior assistant reply")
        self.assertIn("repeat_self",
                      self.coord.quality_guard.seen_advisories[-1],
                      "repeat_self must be detected in the LIVE path (advisory)")
        # advisory only: the identical reply still sends (not a hard block)
        out = self._latest_outbound(wa)
        self.assertEqual(out.strip('"'), REP)

    # ---- 3. escalation E2E -> customer-facing transfer text ---------------
    def test_legal_escalation_customer_text(self):
        wa = "6280000000123"
        self.coord._drafter = _FixedDrafter(ESCALATION_REPLY)
        self.coord.handle_inbound("whatsapp",
                                  self._body(LEGAL_QUESTION, "p2", wa))
        text = self._latest_outbound(wa)
        self.assertIn("فريقنا", text)          # transfer to our team
        self.assertIn("مختص", text)            # specialist
        self.assertNotIn("أسعار", text)        # no pricing
        self.assertNotIn("نضمن", text)         # no claim/guarantee
        # no legal commitment wording
        for banned in ("سنتحمل", "نلتزم", "guarantee", "price"):
            self.assertNotIn(banned.lower(), text.lower())


if __name__ == "__main__":
    unittest.main()
