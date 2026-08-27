"""P0-4 — Support lane is live + opted-out leads never get AI replies."""

from __future__ import annotations

import unittest

from amancore.agents.sales import SalesAgent
from amancore.agents.support import SupportAgent
from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.conversation import ConversationModel
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
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_brain, make_db

WA = "551100777"


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


class SupportAndOptoutTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "p04.db")
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(self.db)
        chpolicy = ChannelPolicyEngine(self.brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=self.audit, dispatcher=self.dispatcher)
        self.crm = CRMService(self.db)
        memory = ConversationMemory(self.crm)
        handover = HandoverService(self.crm, self.dispatcher)
        sales = SalesAgent(self.brain, self.crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(self.brain),
                           FollowupEngine(), HandoffService(self.dispatcher),
                           audit=self.audit, dispatcher=self.dispatcher)
        support = SupportAgent(
            self.brain, self.crm, SupportCaseStore(self.db), handover,
            owner_alert=lambda *a, **k: None, dispatcher=self.dispatcher)
        self.coord = MessageCoordinator(
            adapter, outbox, worker, sales, self.crm, memory,
            handover, ExternalResponseFilter(), chpolicy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=self.audit, dispatcher=self.dispatcher,
            conversation=ConversationModel(self.tmp, self.brain),
            support_agent=support)
        self.drafter = _Cap()
        self.coord._drafter = self.drafter

        def _record(direction, channel, external_user_id, lead_id,
                    external_message_id=None, body="",
                    quoted_external_message_id=None, **_):
            from amancore.ids import utcnow

            self.db.execute(
                "INSERT INTO channel_messages (direction, channel, external_user_id,"
                " lead_id, external_message_id, body, status, created_at,"
                " quoted_external_message_id) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)",
                (direction, channel, external_user_id, lead_id,
                 external_message_id, body, utcnow(),
                 quoted_external_message_id or None))
            self.db.commit()

        self.coord.message_recorder = _record

    def _cases_count(self):
        row = self.db.execute("SELECT COUNT(*) c FROM support_cases").fetchone()
        return row["c"]

    def test_existing_customer_support_intent_opens_case(self):
        # first message makes him a lead; win a deal to turn lead → customer
        self.coord.handle_inbound("whatsapp", _body("أريد موقع لجمعية", "m1"))
        lead_id = self.db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (WA,)).fetchone()["lead_id"]
        # qualify fast: feed the five readiness facts through memory
        mem = ConversationMemory(self.crm).get_or_create(lead_id)
        mem["facts"].update({"problem": "stated", "desired_outcome": "stated",
                             "authority": "owner/decision-maker",
                             "budget": "$5000", "timeline": "next month"})
        ConversationMemory(self.crm).save(mem)
        self.coord.handle_inbound("whatsapp", _body("تمام، ميزانيتنا 5000$ ونبدأ الشهر القادم، أنا المالك", "m2"))
        opp = self.crm.get_opportunity_for_lead(lead_id)
        self.assertIsNotNone(opp)
        self.crm.won_opportunity(opp["opportunity_id"], company="Test Co")
        summary = self.coord.handle_inbound(
            "whatsapp", _body("عندي مشكلة في لوحة التحكم لا تفتح", "m3"))
        self.assertEqual(summary["support"], 1)
        self.assertEqual(self._cases_count(), 1)

    def test_legal_intent_prospect_opens_case_and_escalates(self):
        summary = self.coord.handle_inbound(
            "whatsapp", _body("أريد التحدث بشأن قضية قانونية بخصوص العقد", "m1"))
        self.assertEqual(summary["support"], 1)
        self.assertEqual(self._cases_count(), 1)

    def test_opted_out_lead_never_gets_ai_reply_again(self):
        r1 = self.coord.handle_inbound("whatsapp", _body("أوقف الرجاء", "m1"))
        self.assertEqual(r1["optouts"], 1)
        before = len(self.drafter.messages)
        lead_id = self.db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (WA,)).fetchone()["lead_id"]
        self.assertEqual(self.crm.get_lead(lead_id)["opt_out"], 1)

        r2 = self.coord.handle_inbound("whatsapp", _body("مرحبا كيف الحال؟", "m2"))
        self.assertEqual(r2["replies"], 0)                    # no AI reply
        self.assertEqual(len(self.drafter.messages), before)  # LLM untouched
        inbound_rows = self.db.execute(
            "SELECT COUNT(*) c FROM channel_messages WHERE direction='in'"
        ).fetchone()["c"]
        self.assertEqual(inbound_rows, 2)                     # still recorded


if __name__ == "__main__":
    unittest.main()
