"""P0 LIVE-PARITY regression — the production composition point itself.

These tests call build_conversation_stack() — the SAME function build_runtime
uses — so the tested path and the WhatsApp live path cannot drift. Pins the
full canonical 5-message trace and the price-intent routing.

Root-cause guard: this file exists because the first live run after P0 hit
STALE PROCESSES (started 17:53, code written 19:03+) — plus a real regex gap
(«كم سيكلفني» never matched _PRICE_INTENT).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.webhook_server import build_conversation_stack
from amancore.conversation.pricing_flow import QuoteFlow  # noqa: F401 parity
from amancore.crm.service import CRMService
from amancore.ops.cost_governor import CostGovernor
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db

WA = "905000000901"
ASSOC = "أريد بناء موقع لجمعية اسمها يمن تعاون"


def _body(text, msg_id, wa=WA):
    return {"object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": wa}],
                "messages": [{"from": wa, "id": msg_id, "type": "text",
                              "text": {"body": text}}]}}]}]}


class _Cap:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)

        class _O:
            text = "تم"

        return _O()


class LiveParityTests(TempDirTestCase, unittest.TestCase):
    """Canonical trace through THE production stack builder."""

    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "parity.db")
        crm = CRMService(self.db)
        audit = AuditService(self.db)
        dispatcher = EventDispatcher()
        alerts = []
        stack = build_conversation_stack(
            self.tmp, self.db, self.brain, crm, dispatcher, audit,
            shared_router=FakeRouter({"extraction": "{}"}),
            owner_alert=lambda *a, **k: alerts.append(a))
        from amancore.channels.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(self.db)
        chpolicy = ChannelPolicyEngine(self.brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=audit, dispatcher=dispatcher)
        handover = HandoverService(crm, dispatcher)
        self.coord = MessageCoordinator(
            {"whatsapp": adapter}, outbox, worker, stack["sales"], crm,
            stack["memory"], handover, ExternalResponseFilter(), chpolicy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=audit, dispatcher=dispatcher,
            cost_governor=CostGovernor({}),
            conversation=stack["conversation"],
            quote_flow=stack["quote_flow"],
            support_agent=stack["support"])
        self.drafter = _Cap()
        self.coord._drafter = self.drafter
        self.crm = crm

    def _send(self, text, mid):
        return self.coord.handle_inbound("whatsapp", _body(text, mid))

    def _prompt(self, n=-1):
        return str(self.drafter.messages[n])

    # ---- required CRITICAL TEST (plan-level assertions) -----------------
    def test_association_plan_contract(self):
        model = self.coord.conversation
        plan = model.plan(lead={"lead_id": "L", "industry": None},
                          mem={"facts": {}}, agent_result={},
                          text=ASSOC, language="ar", channel="whatsapp")
        self.assertEqual(plan["service_category"], "website")
        self.assertEqual(plan["industry"], "association_ngo")
        self.assertEqual(plan["mode"], "NEED")
        self.assertTrue(plan["value_payload"].get("sections"))
        brief_q = plan["brief"].count("?") + plan["brief"].count("؟")
        self.assertLessEqual(brief_q, 2)   # hint quoted once => <=1 asked question
        self.assertNotIn("challenge with how you currently", plan["brief"].lower())

    def test_discovery_engine_never_reaches_prompt_when_planned(self):
        from amancore.sales.discovery import DiscoveryEngine

        orig = DiscoveryEngine.next_question
        DiscoveryEngine.next_question = lambda self_, mem: \
            "What's the biggest challenge with how you currently do this?"
        try:
            self._send("مرحبا", "p0")
            self._send(ASSOC, "p1")
        finally:
            DiscoveryEngine.next_question = orig
        prompt = self._prompt()
        self.assertIn("كيف تتبرع", prompt)              # value-first payload
        self.assertNotIn("challenge with how you currently", prompt.lower())
        self.assertNotIn("DISCOVERY PLAYBOOK", prompt)

    # ---- full canonical trace -------------------------------------------
    def test_canonical_trace_five_messages(self):
        self._send("مرحبا", "t0")
        self.assertIn("MODE=OPENING", self._prompt())
        self.assertNotIn("challenge with how you currently",
                         self._prompt().lower())

        self._send(ASSOC, "t1")
        p1 = self._prompt()
        self.assertIn("MODE=NEED", p1)
        self.assertIn("كيف تتبرع", p1)
        self.assertIn("ONE high-value question", p1)
        wm = self.coord.conversation and None
        row = self.db.execute(
            "SELECT working_memory FROM conversations").fetchone()
        self.assertIn('"mode"', row["working_memory"] or "")

        self._send("كل ما ذكرته", "t2")
        p2 = self._prompt()
        self.assertIn("MODE=SHAPING", p2)
        self.assertIn("Business Website System", p2)

        self._send("لا أدري، اقترح لي", "t3")
        p3 = self._prompt()
        # SUGGEST-INTAKE: one easy-choice question first, no full dump yet
        self.assertIn("Before proposing", p3)
        self.assertIn("بوابة تبرع إلكترونية", p3)      # ready-made options
        self.assertNotIn("asked YOU to decide", p3)

        self._send("بوابة تبرع إلكترونية وعربي وإنجليزي", "t4")
        p4 = self._prompt()
        # both clarifiers answered in one message -> FULL tailored proposal
        self.assertIn("asked YOU to decide", p4)
        for section in ("كيف تتبرع", "برامجنا"):
            self.assertIn(section, p4)
        self.assertIn("بوابة تبرع", p4.split("Base it on their choices:")[-1])

        summary = self._send("كم سيكلفني؟", "t5")
        p4 = self._prompt()
        # commercial path engaged — never a discovery structure/question turn
        self.assertNotIn("MODE=NEED", p4)
        self.assertTrue(
            ("official quote" in p4) or ("TENTATIVE ESTIMATE" in p4) or
            ("tier=" in p4), p4[:400])
        self.assertEqual(summary["processed"], 1)

    def test_price_after_scope_goes_t2_not_discovery(self):
        self._send("مرحبا", "q0")
        self._send(ASSOC + " مع بوابة تبرع", "q1")
        lead_id = self.db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (WA,)).fetchone()["lead_id"]
        mem = self.coord.memory.get_or_create(lead_id)
        mem["facts"].update({"scope": "بوابة تبرع وتقارير",
                             "timeline": "بعد شهرين"})
        self.coord.memory.save(mem)
        self._send("كم سيكلفني؟", "q2")
        p = self._prompt()
        self.assertIn("TENTIMATE OR T2".replace("TENTIMATE OR T2",
                                                "TENTATIVE ESTIMATE"), p)
        flow = self.coord.quote_flow
        self.assertEqual(len(flow.pending()), 1)


class ProductionWiringGuardTests(unittest.TestCase):
    """The live runtime must keep using the shared composition point."""

    def test_build_runtime_uses_conversation_stack(self):
        src = Path(__file__).resolve().parents[2] / "amancore" / "channels" / "webhook_server.py"
        code = src.read_text(encoding="utf-8")
        self.assertIn("stack = build_conversation_stack(", code)
        self.assertIn("conversation=conversation", code)
        self.assertIn("quote_flow=quote_flow", code)
        self.assertIn("support_agent=support", code)

    def test_price_regex_covers_sekolif_forms(self):
        from amancore.channels.coordinator import _PRICE_INTENT

        for sample in ("كم سيكلفني؟", "كم يكلف الموقع", "بكم", "كم تكلف"):
            self.assertRegex(sample, _PRICE_INTENT)


if __name__ == "__main__":
    unittest.main()
