import unittest

from amancore.agents.sales import SalesAgent
from amancore.crm.service import CRMService
from amancore.sales.conversation_memory import ConversationMemory
from amancore.sales.discovery import DiscoveryEngine
from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService
from amancore.sales.qualification import QualificationEngine
from amancore.services.audit import AuditService
from amancore.services.events import EventDispatcher
from amancore.skills.objection_handling import ObjectionHandlingSkill
from tests.common import TempDirTestCase, make_brain, make_db


def build_agent(brain, crm, audit, dispatcher):
    return SalesAgent(
        brain, crm,
        ConversationMemory(crm),
        DiscoveryEngine(),
        QualificationEngine(),
        ObjectionHandlingSkill(brain),
        FollowupEngine(),
        HandoffService(dispatcher),
        router=None, audit=audit, dispatcher=dispatcher,
    )


class SalesFlowTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        self.agent = build_agent(self.brain, self.crm, self.audit, self.dispatcher)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _lead(self):
        lid = self.crm.create_lead(company="Resto", market="indonesia", industry="restaurant", language="id")
        return self.crm.get_lead(lid)

    def test_discovery_then_qualify_then_recommend(self):
        lead = self._lead()
        r1 = self.agent.process_message(lead, "I have a restaurant in Jakarta and want an online ordering system")
        self.assertEqual(r1["state"], "discovery")
        self.assertTrue(r1["next_question"])

        r2 = self.agent.process_message(lead, "I am the owner and my budget is $5000")
        self.assertEqual(r2["state"], "discovery")

        r3 = self.agent.process_message(lead, "I want to increase online orders within 2 weeks")
        self.assertEqual(r3["state"], "offer_recommended")
        self.assertTrue(r3["recommendation"])
        self.assertTrue(r3["lead_score"]["score"] >= 40)
        self.assertTrue(r3["opportunity_id"])

        # CRM updated
        updated = self.crm.get_lead(lead["lead_id"])
        self.assertEqual(updated["lead_stage"], r3["lead_score"]["category"])
        self.assertIsNotNone(self.crm.get_opportunity_for_lead(lead["lead_id"]))

    def test_price_objection(self):
        lead = self._lead()
        self.agent.process_message(lead, "I have a restaurant and want a website")
        r = self.agent.process_message(lead, "this is too expensive")
        self.assertEqual(r["objection"], "price_high")
        self.assertTrue(r["objection_response"]["clarification"])

    def test_handoff(self):
        lead = self._lead()
        r = self.agent.process_message(lead, "I want to talk to a human please")
        self.assertTrue(r["needs_human"])
        self.assertIsNotNone(r["handoff"])

    def test_does_not_repeat_questions(self):
        lead = self._lead()
        r1 = self.agent.process_message(lead, "I have a restaurant and want a website")
        q1 = r1["next_question"]  # outcome question
        # answer the asked question → next question must differ
        r2 = self.agent.process_message(lead, "I want to increase online orders")
        self.assertNotEqual(r2["next_question"], q1)


if __name__ == "__main__":
    unittest.main()
