import json
import unittest
from pathlib import Path

import yaml

from amancore.agents.sales import SalesAgent
from amancore.agents.support import SupportAgent
from amancore.analytics.service import AnalyticsService
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

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent.parent
WA_ID = "553300000"


def make_webhook(text, msg_id, wa_id):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": wa_id, "profile": {"name": "Test"}}],
            "messages": [{"from": wa_id, "id": msg_id, "type": "text", "text": {"body": text}}],
        }}]}],
    }


class Phase3FEvals(TempDirTestCase, unittest.TestCase):
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
        support_policy = yaml.safe_load((ROOT / "configs" / "support.yaml").read_text(encoding="utf-8"))
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

    def _make_customer(self, wa_id, company="Co"):
        lead_id = self.crm.create_lead(contact_whatsapp=wa_id, name="Test")
        opp = self.crm.get_opportunity(self.crm.create_opportunity(lead_id, "website_standard"))
        cust = self.crm.won_opportunity(opp["opportunity_id"], company)
        self.crm.update_project(cust["project_id"], status="in_progress")
        return lead_id

    def test_phase3f_scenarios(self):
        scenarios = json.loads((FIXTURES / "phase3f_scenarios.json").read_text())["scenarios"]
        for i, sc in enumerate(scenarios):
            wa_id = f"5533000{i}"
            if sc.get("setup") == "customer":
                self._make_customer(wa_id)
            if sc.get("expect", {}).get("ai_blocked"):
                HandoverService(self.crm).activate_human(
                    self.crm.find_lead_by_whatsapp(wa_id)["lead_id"]
                )
            mid = f"3f-{i}"
            summary = None
            for msg in sc["messages"]:
                summary = self.coord.handle_whatsapp_webhook(make_webhook(msg, mid, wa_id))
                mid += "-n"
            exp = sc["expect"]
            if exp.get("domain") == "sales":
                self.assertEqual(summary["support"], 0, sc["id"])
            elif exp.get("domain") == "support":
                self.assertEqual(summary["support"], 1, sc["id"])
            if exp.get("category"):
                case = self.cases.list(lead_id=self.crm.find_lead_by_whatsapp(wa_id)["lead_id"])[0]
                self.assertEqual(case["category"], exp["category"], sc["id"])
            if exp.get("escalated"):
                case = self.cases.list(lead_id=self.crm.find_lead_by_whatsapp(wa_id)["lead_id"])[0]
                self.assertEqual(case["escalated"], 1, sc["id"])
            if exp.get("critical"):
                case = self.cases.list(lead_id=self.crm.find_lead_by_whatsapp(wa_id)["lead_id"])[0]
                self.assertEqual(case["priority"], "CRITICAL", sc["id"])
            if exp.get("owner_alert"):
                self.assertTrue(self.alerts, sc["id"])
            if exp.get("ai_blocked"):
                self.assertEqual(len(self.adapter.provider.sent), 0, sc["id"])
            self.adapter.provider.sent.clear()
            self.alerts.clear()

    def test_analytics_eval_revenue_margin(self):
        """Analytics eval: revenue + true cost + margin computed correctly."""
        lead_id = self.crm.create_lead(source_channel="whatsapp")
        opp_id = self.crm.create_opportunity(lead_id, "website_standard")
        PricingSnapshotStore(self.db).create(
            opp_id,
            {"currency": "USD", "true_cost": 800, "pricing_policy_version": "v1"},
            approved_price=2000, approved_by="owner", business_brain_version=1,
        )
        self.crm.won_opportunity(opp_id, "Co")
        svc = AnalyticsService(self.db)
        self.assertEqual(svc.revenue()["value"], 2000)
        self.assertEqual(svc.true_cost()["value"], 800)
        self.assertEqual(svc.gross_margin()["value"], 0.6)

    def test_support_sla_policy_loaded(self):
        policy = yaml.safe_load((ROOT / "configs" / "support.yaml").read_text(encoding="utf-8"))
        pp = policy["support_policy"]["priority"]
        self.assertEqual(pp["complaint"], "HIGH")
        self.assertEqual(pp["security_incident"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
