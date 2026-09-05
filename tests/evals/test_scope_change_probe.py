"""SCOPE-CHANGE PATCH (P0.3) — verification tests.

Closing GAP-1..4 from the scope-change probe. Tests exercise the production
composition root (``build_conversation_stack``) with the versioned
``knowledge/`` layer so the tested path and the live path cannot drift.
"""

from __future__ import annotations

import hashlib
import shutil
import unittest
from pathlib import Path
from unittest import mock

from amancore.channels.canonical import InboundMessage
from amancore.channels.coordinator import MessageCoordinator, new_id
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.webhook_server import build_conversation_stack
from amancore.crm.service import CRMService
from amancore.ops.cost_governor import CostGovernor
from amancore.pricing import registry
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db

REPO = Path(__file__).resolve().parents[2]
WA = "6280000000000"
_LEARNINGS = REPO / "amancore" / "business_brain" / "data" / "learnings.jsonl"


class _PlanSpy:
    def __init__(self, planner):
        self._planner = planner
        self.plans = []

    def plan(self, *a, **k):
        p = self._planner.plan(*a, **k)
        self.plans.append(p)
        return p


class _BaseDrafter:
    """Drafter that returns the DRAFT CONTENT (base) from the last message,
    making the outbound reflect the intended pipeline output."""

    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        for m in reversed(messages):
            if m.get("role") == "user":
                marker = "DRAFT CONTENT: "
                i = (m.get("content") or "").find(marker)
                if i >= 0:
                    base = m["content"][i + len(marker):].split("\n\n")[0].strip()
                    if base:
                        return type("R", (), {"text": base})()
        return type("R", (), {"text": "تم"})()


class ScopeChangePatch(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "knowledge", self.tmp / "knowledge")
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "patch.db")
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        self.alerts = []
        stack = build_conversation_stack(
            self.tmp, self.db, self.brain, self.crm, self.dispatcher,
            self.audit, shared_router=FakeRouter({"extraction": "{}"}),
            owner_alert=lambda *a, **k: self.alerts.append(a))
        self.model = stack["conversation"]
        self.memory = stack["memory"]
        self.quote_flow = stack["quote_flow"]
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
        self.coord._drafter = _BaseDrafter()
        self.spy = _PlanSpy(self.model.planner)
        self.model.planner = self.spy

    def _body(self, text, mid):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "905345247791"},
                    "contacts": [{"wa_id": WA}],
                    "messages": [{"from": WA, "id": mid, "type": "text",
                                  "text": {"body": text}}]}}]}]}

    def _outbound(self):
        row = self.db.execute(
            "SELECT payload FROM message_outbox WHERE recipient=?"
            " AND message_type='text' ORDER BY created_at DESC LIMIT 1",
            (WA,)).fetchone()
        return (row["payload"] or "") if row else ""

    def _drive(self, text, mid):
        self.coord._drafter = _BaseDrafter()
        self.coord.handle_inbound("whatsapp", self._body(text, mid))
        return self._outbound()

    def _mem(self):
        lead = self.crm.find_lead_by_whatsapp(WA)
        return self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar"), lead

    def _approve_website_snapshot(self, scope_facts, lead_id, small=True):
        """Create an approved website snapshot (shared by B / D / sabotage tests)."""
        mem = self.memory.get_or_create(lead_id, "whatsapp", "ar")
        mem["facts"] = dict(mem.get("facts") or {}, **scope_facts)
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="website", small_scope=small)
        self.memory.save(mem)
        lead = self.crm.get_lead(lead_id)
        fp = registry.scope_fingerprint("website", scope_facts, small=small)
        est = self.quote_flow.estimate(lead, "website", hours_override=6)
        appr = self.quote_flow.request_owner_approval(
            lead, est, corr=new_id(), scope_fingerprint=fp)
        snap_id = self.quote_flow.finalize(appr, "probe_owner")
        snap = self.snapshots.get(snap_id)
        self.assertEqual(snap["status"], "approved")
        return snap_id, float(snap["approved_price"]), fp

    # ---- A) literal 4-turn scenario (capture works now) -----------------
    def test_A_literal_scope_change_scenario(self):
        T1 = "عندي مطعم وأبغى موقع بسيط مع قائمة الطعام"
        T2 = "أبغى المنيو الإلكتروني مهم، حوالي 6 صفحات، المحتوى جاهز، نسلم خلال شهر"
        T3 = "أبغى أضيف كمان نظام حجز طاولات وطلبات أونلاين"
        T4 = "طيب كم صار السعر الآن؟"

        self._drive(T1, "a1")
        p1 = self.spy.plans[-1]
        self._drive(T2, "a2")
        p2 = self.spy.plans[-1]
        r3 = self._drive(T3, "a3")
        p3 = self.spy.plans[-1]
        r4 = self._drive(T4, "a4")
        p4 = self.spy.plans[-1]
        mem, _ = self._mem()

        self.assertEqual(p1["industry"], "restaurant")
        for p in (p1, p2, p3):
            self.assertLessEqual(len([c for c in p["brief"] if c in "؟?"]), 2)
        # GAP-1: capture now works
        self.assertIn("booking", mem.get("facts"))
        self.assertIn("payments", mem.get("facts"))
        # GAP-3: recap fires on scope-change turn
        self.assertIn("Active listening", p3["brief"])
        # GAP-3.2: no inverted "booking later" suggestion
        self.assertNotIn("booking system later as an extension", p3["brief"])
        # GAP-2/4: T4 produces a fresh figure from Brain (business_system band
        # 12100-42600) via the T1 band path, not the silent deferral "تم" or
        # an old number.  With _BaseDrafter the outbound IS the band text.
        self.assertIn("12100", r4)   # business_system low
        self.assertIn("42600", r4)   # business_system high
        self.assertNotIn("The approved price", r4)

    # ---- B) controlled invalidation: approved snapshot + scope change ----
    def test_B_approved_snapshot_invalidation_no_leak(self):
        lead = self.crm.find_lead_by_whatsapp(WA)
        self._drive("عندي مطعم وأبغى موقع بسيط مع قائمة الطعام", "b0")
        lead = self.crm.find_lead_by_whatsapp(WA)

        S1 = {"scope": "موقع بسيط بقائمة طعام", "timeline": "شهر"}
        snap_id, old_high, fp1 = self._approve_website_snapshot(
            S1, lead["lead_id"])

        # Scope S2: add table booking + online ordering
        S2 = {"scope": "موقع بقائمة وحجز طاولات وطلبات أونلاين", "timeline": "شهر"}
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["facts"] = dict(mem.get("facts") or {}, **S2)
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="website", small_scope=True)
        self.memory.save(mem)
        fp2 = registry.scope_fingerprint("website", S2, small=True)
        self.assertNotEqual(fp1, fp2, "changed scope must change fingerprint")

        pm = InboundMessage(channel="whatsapp", external_message_id="b1",
                            external_user_id=WA, text="طيب كم صار السعر الآن؟")
        reply = self.coord._price_or_proposal_reply(lead, new_id(), msg=pm)
        refreshed = self.snapshots.get(snap_id)
        # "The approved price" phrase must not appear (the old number might
        # coincidentally match a fresh Brain figure — only the phrase leaks)
        self.assertNotIn("The approved price", reply)
        self.assertEqual(refreshed["status"], "superseded")
        self.assertEqual(refreshed["superseded_by"], "scope_change")
        self.assertTrue(reply)

    # ---- C) natural scope-delta captured (GAP-1 fixed) ------------------
    def test_C_natural_scope_delta_captured(self):
        self._drive("عندي مطعم وأبغى موقع بسيط مع قائمة الطعام", "c0")
        lead = self.crm.find_lead_by_whatsapp(WA)
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["facts"] = dict(mem.get("facts") or {}, scope="موقع بسيط بقائمة طعام")
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="website", small_scope=True)
        self.memory.save(mem)
        fp_before = registry.scope_fingerprint(
            "website", mem["facts"], small=True)

        self._drive("أبغى أضيف كمان نظام حجز طاولات وطلبات أونلاين", "c1")
        mem_after = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        facts = mem_after.get("facts") or {}
        fp_after = registry.scope_fingerprint(
            "website", facts, small=True)

        # GAP-1: capture works — booking and payments are now in facts
        self.assertTrue(facts.get("booking"), "booking must be captured")
        self.assertTrue(facts.get("payments"), "payments must be captured")
        self.assertNotEqual(fp_before, fp_after,
                            "scope delta must change the fingerprint")

    # ---- D) in-category scope change (no category drift) ----------------
    def test_D_in_category_scope_change(self):
        self._drive("عندي موقع تعريفي بسيط", "d0")
        lead = self.crm.find_lead_by_whatsapp(WA)

        S1 = {"scope": "موقع تعريفي من صفحة إلى ثلاث", "timeline": "شهر",
              # D2-APPROVED Gate-B+: connect + authority/budget join the seed
              # (stand-ins for prior discovery turns).
              "budget": "3000$"}
        snap_id, old_high, fp1 = self._approve_website_snapshot(
            S1, lead["lead_id"])

        # Add gallery/news within same category (website)
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        wm = dict(mem.get("working_memory") or {},
                  service_category="website", small_scope=True)
        wm["scope_review_fields"] = []
        wm["scope_under_review"] = False
        mem["working_memory"] = wm
        self.memory.save(mem)

        # drive the delta message through coordinator (update_scope_review + extract_facts)
        self._drive("أبغى أضيف معرض صور وأخبار للعناصر وربط الدفع", "d1")
        mem_after = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        self.assertTrue((mem_after.get("facts") or {}).get("dynamic_content"),
                        "dynamic_content must be captured")
        fp2 = registry.scope_fingerprint(
            "website", mem_after.get("facts") or {}, small=True)
        self.assertNotEqual(fp1, fp2,
                            "fingerprint must change without category drift")

        # price ask — old number superseded, fresh estimate shown
        self._drive("كم صار السعر الآن؟", "d2")
        r4 = self._outbound()
        # category remains website → T2 small-scope estimate. Under the
        # D2-APPROVED gate the richer scope (gallery + payments) prices at
        # 500-1500 USD (deterministic dynamic hours, no AI in probe).
        self.assertIn("500", r4)   # website T2 low
        self.assertIn("1500", r4)  # website T2 high
        self.assertNotIn("The approved price", r4)

    # ---- E) band-less category (GAP-2 fires) ----------------------------
    def test_E_bandless_category_requirement_reply(self):
        """branding has NO public band — the price path must produce a
        deterministic requirement question, never a silent deferral."""
        self._drive("أريد هوية بصرية وموقع تعريفي للعلامة التجارية", "e0")
        lead = self.crm.find_lead_by_whatsapp(WA)
        mem = self.memory.get_or_create(lead["lead_id"], "whatsapp", "ar")
        mem["working_memory"] = dict(mem.get("working_memory") or {},
                                     service_category="branding",
                                     small_scope=False)
        self.memory.save(mem)
        pm = InboundMessage(channel="whatsapp", external_message_id="e1",
                            external_user_id=WA, text="كم التكلفة؟")
        reply = self.coord._price_or_proposal_reply(lead, new_id(), msg=pm)
        # must contain an Arabic question mark (one question)
        self.assertIn("؟", reply)
        # no price number, no silent deferral
        self.assertNotIn("approved price", reply)
        self.assertNotIn("The approved price", reply)

    # ---- Sabotage A: capture removed, invariant still blocks -------------
    def test_sabotage_a_capture_removed_invariant_blocks(self):
        """Even if _deterministic_facts doesn't capture scope-delta (capture
        disabled), the scope_under_review invariant still blocks the old
        number.  If someone removes the invariant gate, the old number would
        leak and this test would fail."""
        self._drive("عندي مطعم وأبغى موقع بسيط", "s0")
        lead = self.crm.find_lead_by_whatsapp(WA)

        S1 = {"scope": "موقع بسيط بقائمة طعام", "timeline": "شهر"}
        snap_id, old_high, _ = self._approve_website_snapshot(
            S1, lead["lead_id"])

        # Monkeypatch: disable capture (scope-delta facts NOT filled)
        import amancore.sales.conversation_memory as cm
        original = cm._deterministic_facts

        def _stripped(message):
            facts = original(message)
            for field in ("booking", "payments", "dynamic_content",
                          "integrations", "languages", "member_areas"):
                facts.pop(field, None)
            return facts

        with mock.patch.object(cm, "_deterministic_facts", _stripped):
            self._drive("أبغى أضيف كمان نظام حجز طاولات وطلبات أونلاين", "s1")
            mem_after = self.memory.get_or_create(
                lead["lead_id"], "whatsapp", "ar")
            wm = mem_after.get("working_memory") or {}
            # review must be active (pending fields unresolved)
            self.assertTrue(wm.get("scope_under_review"),
                            "scope_under_review must be True when capture is removed")
            self.assertTrue(wm.get("scope_review_fields"))
            # facts must NOT contain the delta (capture is off)
            self.assertFalse((mem_after.get("facts") or {}).get("booking"),
                             "booking must NOT be in facts (capture removed)")
            # price ask — old number must NOT leak
            pm = InboundMessage(channel="whatsapp", external_message_id="s2",
                                external_user_id=WA,
                                text="طيب كم صار السعر الآن؟")
            reply = self.coord._price_or_proposal_reply(lead, new_id(), msg=pm)
            self.assertNotIn("The approved price", reply)
            self.assertNotIn(f"{old_high:g}", reply)
            self.assertIn("؟", reply, "must ask a clarifying question, not show old number")

    # ---- Sabotage B: language passed correctly (GAP-4) ------------------
    def test_sabotage_b_language_passed(self):
        """_t1/_t2 memory must be fetched with the conversation language,
        not a hardcoded 'en'.  If reverted, the recorded language would be 'en'
        and the test would fail."""
        self._drive("أريد موقع تعريفي بسيط", "lang0")
        lead = self.crm.find_lead_by_whatsapp(WA)

        lang_calls = []
        original_get = self.memory.get_or_create

        def spy_get(lead_id, channel="internal", language="en"):
            lang_calls.append(language)
            return original_get(lead_id, channel, language)

        with mock.patch.object(self.memory, "get_or_create", spy_get):
            pm = InboundMessage(channel="whatsapp", external_message_id="lang1",
                                external_user_id=WA, text="كم السعر؟")
            self.coord._t1_band_reply(lead, new_id(), msg=pm)

        # at least one call with detected language "ar" (not only "en")
        self.assertTrue(any(l != "en" for l in lang_calls),
                        f"GAP-4: memory must use detected language, not 'en'. "
                        f"Languages seen: {lang_calls}")

    # ---- Learning isolation (0.1) + hash proof ---------------------------
    def test_learning_isolation(self):
        """Production learnings.jsonl must not be modified by the test suite."""
        _JOURNAL = Path(__import__("amancore.ops.learning", fromlist=["_JOURNAL"])._JOURNAL)
        self.assertNotEqual(_JOURNAL, _LEARNINGS,
                            "production _JOURNAL must be redirected during tests")

        # record a learning via the isolated journal
        from amancore.ops.learning import record_learning
        record_learning("test_isolation", "test message", "test reply")
        # production file unchanged
        if _LEARNINGS.exists():
            prod_hash = hashlib.sha256(
                _LEARNINGS.read_bytes()).hexdigest()
            record_learning("test2", "test msg2", "test reply2")
            prod_hash_after = hashlib.sha256(
                _LEARNINGS.read_bytes()).hexdigest()
            self.assertEqual(prod_hash, prod_hash_after,
                             "production learnings.jsonl must not change")


if __name__ == "__main__":
    unittest.main()
