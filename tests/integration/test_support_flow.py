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
from amancore.crm.service import CRMService
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.sales.conversation_memory import ConversationMemory
from amancore.sales.discovery import DiscoveryEngine
from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService
from amancore.sales.qualification import QualificationEngine
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from amancore.skills.objection_handling import ObjectionHandlingSkill
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_brain, make_db

WA_ID = "552200000"


def webhook_body(text, msg_id, wa_id=WA_ID):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": wa_id, "profile": {"name": "Test"}}],
            "messages": [{"from": wa_id, "id": msg_id, "type": "text", "text": {"body": text}}],
        }}]}],
    }


class SupportFlowIntegrationTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        self.outbox = MessageOutbox(self.db)
        policy = ChannelPolicyEngine(self.brain)
        self.worker = OutboxWorker(self.outbox, {"whatsapp": self.adapter}, policy, dispatcher=self.dispatcher)
        memory = ConversationMemory(self.crm)
        sales = SalesAgent(
            self.brain, self.crm, memory, DiscoveryEngine(), QualificationEngine(),
            ObjectionHandlingSkill(self.brain), FollowupEngine(), HandoffService(self.dispatcher),
            router=None, dispatcher=self.dispatcher,
        )
        self.alerts = []
        from pathlib import Path

        import yaml

        support_policy = yaml.safe_load(
            (Path(__file__).resolve().parent.parent.parent / "configs" / "support.yaml").read_text(encoding="utf-8")
        )
        self.support = SupportAgent(
            self.brain, self.crm, SupportCaseStore(self.db), HandoverService(self.crm, self.dispatcher),
            owner_alert=lambda lvl, msg, corr: self.alerts.append((lvl, msg)),
            support_policy=support_policy, dispatcher=self.dispatcher,
        )
        self.coord = MessageCoordinator(
            self.adapter, self.outbox, self.worker, sales, self.crm, memory,
            HandoverService(self.crm, self.dispatcher), ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(router=None),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda lvl, msg, corr: self.alerts.append((lvl, msg)),
            dispatcher=self.dispatcher, support_agent=self.support,
        )
        self.cases = SupportCaseStore(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _make_customer(self, wa_id=WA_ID, company="Co"):
        lead_id = self.crm.create_lead(contact_whatsapp=wa_id, name="Test")
        opp = self.crm.get_opportunity(self.crm.create_opportunity(lead_id, "website_standard"))
        cust = self.crm.won_opportunity(opp["opportunity_id"], company)
        self.crm.update_project(cust["project_id"], status="in_progress", milestones='["design done"]')
        return self.crm.get_lead(lead_id), self.crm.get_customer(cust["customer_id"])

    def test_existing_customer_project_status(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("how is my project going?", "s-1"))
        self.assertEqual(summary["support"], 1)
        sent = self.adapter.provider.sent[-1]["payload"]
        self.assertIn("in_progress", sent)
        self.assertTrue(self.adapter.provider.sent)

    def test_billing_refund_escalates(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("I want a refund please", "s-2"))
        self.assertEqual(summary["support"], 1)
        self.assertEqual(summary["handoffs"], 1)
        cases = self.cases.list()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["category"], "billing")
        self.assertEqual(cases[0]["escalated"], 1)
        self.assertEqual(HandoverService(self.crm).get_mode(self.crm.find_lead_by_whatsapp(WA_ID)["lead_id"]), "HUMAN_REQUESTED")
        self.assertTrue(any(lvl == "high" for lvl, _ in self.alerts))

    def test_legal_escalates_to_owner(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("I will take legal action", "s-3"))
        self.assertEqual(summary["support"], 1)
        self.assertEqual(self.cases.list()[0]["category"], "legal")
        self.assertEqual(self.cases.list()[0]["escalated"], 1)

    def test_security_critical(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("there is a security incident, data breach!", "s-4"))
        self.assertEqual(summary["support"], 1)
        case = self.cases.list()[0]
        self.assertEqual(case["priority"], "CRITICAL")
        self.assertEqual(case["escalated"], 1)
        self.assertTrue(any(lvl == "critical" for lvl, _ in self.alerts))

    def test_prospect_support_message_routes_to_sales(self):
        # no customer -> "help me build a website" is a prospect, stays in sales
        summary = self.coord.handle_whatsapp_webhook(webhook_body("help me build a website please", "s-5"))
        self.assertEqual(summary["support"], 0)
        self.assertTrue(self.adapter.provider.sent)

    def test_customer_new_purchase_routes_to_sales(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("I want to buy another website", "s-6"))
        self.assertEqual(summary["support"], 0)

    def test_support_reply_has_no_leak(self):
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("how is my project going?", "s-7"))
        sent = " ".join(m["payload"] for m in self.adapter.provider.sent)
        for term in ("true cost", "shadow rate", "lead score", "risk score", "internal"):
            self.assertNotIn(term, sent)
        self.assertEqual(summary["support"], 1)

    def test_customer_discount_escalates_to_owner(self):
        # customers asking for a discount must reach the owner (support cannot discount)
        self._make_customer()
        summary = self.coord.handle_whatsapp_webhook(webhook_body("can you give me a discount?", "s-9"))
        self.assertEqual(summary["support"], 1)
        case = self.cases.list()[0]
        self.assertEqual(case["escalated"], 1)

    def test_ai_stops_during_human_takeover(self):
        lead, _ = self._make_customer()
        HandoverService(self.crm).activate_human(lead["lead_id"])
        before = len(self.adapter.provider.sent)
        summary = self.coord.handle_whatsapp_webhook(webhook_body("how is my project going?", "s-8"))
        self.assertEqual(len(self.adapter.provider.sent), before)
        self.assertEqual(summary["processed"], 1)


if __name__ == "__main__":
    unittest.main()
