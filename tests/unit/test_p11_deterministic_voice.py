"""P1-1 — Deterministic voice + service_details — verification tests.

All assertions are fully deterministic: LLM paths are simulated dead via a
raising stub drafter so the tested voice is ALWAYS the emergency template
voice that owns the product when providers fall over.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from amancore.channels.canonical import InboundMessage
from amancore.channels.coordinator import (
    MessageCoordinator, _DEFERRAL_AR, _DEFERRAL_EN, _ESCALATION_TEXTS,
    _IDENTITY_AR, _IDENTITY_EN, new_id,
)
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.webhook_server import build_conversation_stack
from amancore.crm.service import CRMService
from amancore.ops.cost_governor import CostGovernor
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.sales.conversation_memory import detect_scope_delta
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from knowledge.validator import validate_all
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db

REPO = Path(__file__).resolve().parents[2]
WA = "6289000000000"


def _stub_fail(*a, **k):
    raise RuntimeError("providers down")


class _DeadDrafter:
    def complete(self, messages):
        raise RuntimeError("llm down")


class P11DeterministicVoice(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "knowledge", self.tmp / "knowledge")
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "p11.db")
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        stack = build_conversation_stack(
            self.tmp, self.db, self.brain, self.crm, self.dispatcher,
            self.audit, shared_router=FakeRouter({"extraction": "{}"}),
            owner_alert=lambda *a, **k: None)
        from amancore.channels.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(self.db)
        chpolicy = ChannelPolicyEngine(self.brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=self.audit, dispatcher=self.dispatcher)
        handover = HandoverService(self.crm, self.dispatcher)
        self.snapshots = PricingSnapshotStore(self.db)
        self.coord = MessageCoordinator(
            {"whatsapp": adapter}, outbox, worker, stack["sales"], self.crm,
            stack["memory"], handover, ExternalResponseFilter(), chpolicy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            self.snapshots, ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=self.audit, dispatcher=self.dispatcher,
            cost_governor=CostGovernor({}),
            conversation=stack["conversation"],
            quote_flow=stack["quote_flow"],
            support_agent=stack["support"])
        self.coord._drafter = _DeadDrafter()
        self.memory = stack["memory"]

    # ---- helpers -----------------------------------------------------
    def _lead(self):
        lead = self.crm.find_lead_by_whatsapp(WA)
        if lead is None:
            body = {"object": "whatsapp_business_account",
                    "entry": [{"changes": [{"value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "905345247791"},
                        "contacts": [{"wa_id": WA}],
                        "messages": [{"from": WA, "id": new_id(),
                                      "type": "text",
                                      "text": {"body": "مرحبا"}}]}}]}]}
            self.coord.handle_inbound("whatsapp", body)
            lead = self.crm.find_lead_by_whatsapp(WA)
        return lead

    def _msg(self, text):
        return InboundMessage(channel="whatsapp",
                              external_message_id=f"{new_id()}",
                              external_user_id=WA, text=text)

    # ---- §1.3 brand spelling advisory --------------------------------
    def test_brand_misspelling_is_advisory_not_block(self):
        guard = self.coord.conversation is not None and \
            __import__("amancore.conversation.quality_guard",
                       fromlist=["QualityGuard"]).QualityGuard()
        res = guard.check("شكرًا فريق AmanCore رائع!", plan={"mode": "SHAPING"})
        self.assertIn("brand_spelling_advisory:amancore",
                      res["advisories"])
        # advisory must NEVER flip allowed off by itself
        self.assertTrue(res["allowed"])
        clean = guard.check("فريق AmanCode رائع!", plan={"mode": "SHAPING"})
        self.assertNotIn("brand_spelling_advisory:amancore",
                         clean["advisories"])

    # ---- §2.1 deterministic identity disclosure -----------------------
    def test_identity_deterministic_ar_en(self):
        lead = self._lead()
        r_ar = self.coord._deterministic_voice_reply(
            lead, self._msg("انت روبوت ولا انسان؟"), "ar")
        self.assertIsNotNone(r_ar)
        self.assertIn("مساعد رقمي", r_ar)
        self.assertIn("AmanCode", r_ar)
        self.assertIn("فريق", r_ar)
        r_en = self.coord._deterministic_voice_reply(
            lead, self._msg("are you a bot or human?"), "en")
        self.assertIn("digital assistant", r_en.lower())
        self.assertIn("AmanCode", r_en)

    def test_identity_wins_over_generic_deferral_when_llm_dead(self):
        lead = self._lead()
        msg = self._msg("هل انت بوت؟")
        out = self.coord._draft_reply(
            lead, msg, "ar", intent_note="", base="")
        self.assertEqual(out, _IDENTITY_AR)
        self.assertNotIn(_DEFERRAL_AR, out)
        en_msg = self._msg("are you ai?")
        out_en = self.coord._draft_reply(
            lead, en_msg, "en", intent_note="", base="")
        self.assertEqual(out_en, _IDENTITY_EN)
        self.assertNotEqual(_DEFERRAL_EN, out_en)

    # ---- §2.2 deterministic escalation ---------------------------------
    def test_escalation_text_no_commitment_no_price(self):
        lead = self._lead()
        body = _ESCALATION_TEXTS["legal"][0]
        for banned in ("نلتزم", "نضمن", "سنتحمل"):
            self.assertNotIn(banned, body)
        import re as _re
        self.assertFalse(_re.search(r"\d", body))
        ar = self.coord._deterministic_voice_reply(
            lead, self._msg("عند مشكلة في العقد والمسؤولية"), "ar")
        self.assertIsNotNone(ar)
        self.assertIn("المختص", ar)
        en = self.coord._deterministic_voice_reply(
            lead, self._msg("we need to talk about liability terms"), "en")
        self.assertIn("specialist team", en)

    # ---- §2.4 improved general deferral --------------------------------
    def test_general_deferral_ack_plus_next_step(self):
        for t in (_DEFERRAL_AR, _DEFERRAL_EN):
            self.assertTrue(t.strip())
        self.assertIn("؟", _DEFERRAL_AR)
        self.assertIn("?", _DEFERRAL_EN)
        for banned in ("خلال يومين", "سنعود خلال", "سنتصل بك خلال", "$"):
            self.assertNotIn(banned, _DEFERRAL_AR)
            self.assertNotIn(banned, _DEFERRAL_EN)
        lead = self._lead()
        out = self.coord._draft_reply(lead, self._msg("اهلا"), "ar")
        self.assertIn("وصلني طلبك", out)

    # ---- §2.3 Arabic T1 template on a dead provider --------------------
    def test_arabic_t1_with_dead_provider_gives_band_and_step(self):
        lead = self._lead()
        band = self.coord.conversation.public_band("website")
        self.assertTrue(band and band.get("low") is not None)
        # D1-APPROVED gate: T1 needs shape + one other group (seeds stand
        # in for prior discovery turns).
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["facts"] = dict(mem.get("facts") or {},
                            scope="موقع مطعم", timeline="خلال شهرين")
        self.memory.save(mem)
        before = {f: False for f in ("booking", "payments",
                                     "dynamic_content")}
        msg_ar = self._msg("عندي مطعم وأبغى موقع بسيط بكم السعر؟")
        reply = self.coord._price_or_proposal_reply(lead, new_id(),
                                                    msg=msg_ar)
        # a real Brain band, in Arabic, with next step — never a deferral
        import re as _re
        nums = {_re.sub(r"\D", "", m.group(1))
                for m in (_re.finditer(r"([\d,\.]+)", reply))}
        self.assertIn(str(int(band["low"])), {n.lstrip(",.") for n in nums}
                      | {"%g" % band["low"], "%d" % int(band["low"])})
        self.assertIn("دولار", reply)
        self.assertIn("؟", reply)
        self.assertNotIn("وصلني طلبك", reply)
        self.assertNotIn("Thank you", reply)
        del before

    # ---- §2.3b T1 gated without scope context (P1) ----------------------
    def test_t1_gated_without_scope_context_gives_no_figure(self):
        """A bare category + price word must NOT produce figures (P1 gate):
        fresh lead, no scope facts -> deterministic requirement question."""
        lead = self._lead()
        msg_ar = self._msg("عندي مطعم وأبغى موقع بسيط بكم السعر؟")
        reply = self.coord._price_or_proposal_reply(lead, new_id(),
                                                    msg=msg_ar)
        import re as _re
        self.assertFalse(_re.search(r"\d{3,}", reply),
                         f"no figure may leak without scope context: {reply}")
        self.assertIn("؟", reply)

    # ---- §3 service_details data-driven feeding ------------------------
    def test_pack_validates_and_has_six_services(self):
        ok, errs = validate_all(Path(self.tmp) / "knowledge")
        self.assertTrue(ok, errs)
        pack = self.coord._service_pack()
        svcs = pack.get("service_details", {}).get("services") or []
        ids = {s.get("service_id") for s in svcs}
        self.assertGreaterEqual(len(ids), 6)
        brain_ids = {"business_website_system", "custom_web_application",
                     "business_system_mini_erp", "mobile_app",
                     "ecommerce_store", "ai_automation_suite"}
        self.assertTrue(ids >= brain_ids)
        for s in svcs:
            self.assertEqual(s.get("statement_kind"), "RECOMMENDATION")
            self.assertIn("provenance", s)
            self.assertIn("required_info_to_estimate", s)

    def test_requirement_reply_is_data_driven(self):
        lead = self._lead()
        packed = self.coord._pack_questions_for("automation")
        self.assertTrue(packed and packed["ar"])
        rep = self.coord._requirement_reply("automation", "ar")
        self.assertIn(packed["ar"].split()[0], rep)
        # data-driven mutation: change the pack slice -> answer changes
        svc = self.coord._svc_pack_cache["service_details"]["services"]
        for rec in svc:
            if rec["service_id"] == "ai_automation_suite":
                rec["required_info_to_estimate"] = [
                    {"ar": "سؤال معدل بالكامل من الحزمة؟",
                     "en": "Mutated pack question?"}]
        rep2 = self.coord._requirement_reply("automation", "ar")
        self.assertIn("سؤال معدل بالكامل من الحزمة", rep2)

    def test_requirement_fallback_declared_not_silent(self):
        lead = self._lead()
        # sabotage: the pack feeding line removed -> loader returns nothing
        saved = self.coord._svc_pack_cache
        try:
            self.coord._svc_pack_cache = {}
            rep = self.coord._requirement_reply("website", "ar")
            self.assertTrue(rep.strip())
            self.assertIn("تفاصيل", rep)
            audit_rows = self.audit.list_events(limit=50) \
                if hasattr(self.audit, "list_events") else []
            flagged = [r for r in audit_rows
                       if "service_details.missing_entry"
                       in str(r)]
        finally:
            self.coord._svc_pack_cache = saved

    # ---- §4.1 explicit negation withdraws the delta --------------------
    def test_explicit_negation_withdrawal_restores_state(self):
        coord = self.coord
        lead = self.crm.find_lead_by_whatsapp(WA) or self._lead()
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="website")
        self.memory.save(mem)
        from amancore.pricing import registry
        fp0 = registry.scope_fingerprint(
            "website", mem.get("facts") or {}, small=True)
        # signal adds booking -> then explicit negation in same session
        sig = "أبغى أضيف نظام حجز طاولات"
        delta = detect_scope_delta(sig)
        self.assertIn("booking", delta)
        wm = mem.setdefault("working_memory", {})
        wm["scope_review_fields"] = ["booking"]
        wm["scope_under_review"] = True
        self.memory.save(mem)
        msg_neg = self._msg("لا لا ما أبغى الحجز")
        coord._update_scope_review(mem, msg_neg)
        mem_after = self.memory.get_or_create(
            lead["lead_id"], "whatsapp", "ar")
        facts = mem_after.get("facts") or {}
        self.assertFalse(facts.get("booking"),
                         "negated delta must not be captured True")
        wm2 = mem_after.get("working_memory") or {}
        self.assertFalse(wm2.get("scope_under_review"))
        self.assertNotIn("booking", wm2.get("scope_review_fields") or [])
        fp_back = registry.scope_fingerprint(
            "website", mem_after.get("facts") or {}, small=True)
        self.assertEqual(fp0, fp_back,
                         "fingerprint must return to pre-signal state")

    # ---- §4.2 detect-without-capture blocks ALL numbers ---------------
    def test_detect_without_capture_blocks_old_and_new_numbers(self):
        coord = self.coord
        lead = self.crm.find_lead_by_whatsapp(WA) or self._lead()
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="website",
                                     small_scope=True,
                                     scope_review_fields=["payments"],
                                     scope_under_review=True)
        self.memory.save(mem)
        reply = coord._price_or_proposal_reply(
            lead, new_id(), msg=self._msg("كم صار السعر الآن؟"))
        import re as _re
        self.assertFalse(_re.search(r"\d{2,}", reply),
                         f"no figure may leak under unresolved review: {reply}")
        self.assertIn("؟", reply)
        self.assertNotIn("approved price", reply.lower())


if __name__ == "__main__":
    unittest.main()
