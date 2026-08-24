import json
import unittest
from pathlib import Path

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
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from amancore.skills.objection_handling import ObjectionHandlingSkill
from tests.common import TempDirTestCase, make_brain, make_db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def make_webhook(text, msg_id, wa_id):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": wa_id, "profile": {"name": "Test"}}],
            "messages": [{"from": wa_id, "id": msg_id, "type": "text", "text": {"body": text}}],
        }}]}],
    }


class ChannelEval(TempDirTestCase, unittest.TestCase):
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
        self.coord = MessageCoordinator(
            self.adapter, self.outbox, self.worker, sales, self.crm, memory,
            HandoverService(self.crm, self.dispatcher), ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(router=None),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda level, msg, corr, **kw: None,
            dispatcher=self.dispatcher,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_channel_scenarios(self):
        scenarios = json.loads((FIXTURES / "channel_scenarios.json").read_text())["scenarios"]
        for i, sc in enumerate(scenarios):
            wa_id = f"5511000{i}"
            mid = f"eval-{i}"
            summary = None
            if sc.get("malformed"):
                summary = self.coord.handle_whatsapp_webhook({"object": "other"})
            else:
                for msg in sc["messages"]:
                    summary = self.coord.handle_whatsapp_webhook(make_webhook(msg, mid, wa_id))
                    mid += "-n"
            if sc.get("duplicate"):
                summary = self.coord.handle_whatsapp_webhook(make_webhook(sc["messages"][0], f"eval-{i}", wa_id))
            exp = sc["expect"]

            if exp.get("lead_created"):
                self.assertIsNotNone(self.crm.find_lead_by_whatsapp(wa_id), sc["id"])
            if exp.get("single_lead"):
                self.assertEqual(len(self.crm.find_lead_by_whatsapp(wa_id) and [1] or []), 1, sc["id"])
            if exp.get("no_invented_price"):
                sent = self.adapter.provider.sent[-1]["payload"] if self.adapter.provider.sent else ""
                self.assertIn("approved quote", sent, sc["id"])
                self.assertNotRegex(sent, r"\$\s?\d", sc["id"])
            if exp.get("objection"):
                lead = self.crm.find_lead_by_whatsapp(wa_id)
                conv = self.crm.get_conversation_for_lead(lead["lead_id"])
                import json as _j

                objections = _j.loads(conv.get("objections") or "[]")
                self.assertIn(exp["objection"], objections, sc["id"])
            if exp.get("handoff"):
                self.assertTrue(self.adapter.provider.sent, sc["id"])
            if exp.get("optout"):
                lead = self.crm.find_lead_by_whatsapp(wa_id)
                self.assertEqual(lead["opt_out"], 1, sc["id"])
            if exp.get("language"):
                lead = self.crm.find_lead_by_whatsapp(wa_id)
                conv = self.crm.get_conversation_for_lead(lead["lead_id"])
                self.assertEqual(conv.get("language"), exp["language"], sc["id"])
            if exp.get("no_duplicate"):
                self.assertEqual(summary["duplicates"], 1, sc["id"])
                same = [l for l in self.crm.search_leads() if l["contact_whatsapp"] == wa_id]
                self.assertEqual(len(same), 1, sc["id"])
            if exp.get("safe_reject"):
                self.assertEqual(summary["processed"], 0, sc["id"])
            self.adapter.provider.sent.clear()

    def test_malformed_webhook(self):
        summary = self.coord.handle_whatsapp_webhook({"object": "other"})
        self.assertEqual(summary["processed"], 0)
        self.assertEqual(len(self.adapter.provider.sent), 0)


if __name__ == "__main__":
    unittest.main()
