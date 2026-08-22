import json
import unittest
from pathlib import Path

from amancore.agents.sales import SalesAgent
from amancore.crm.service import CRMService
from amancore.sales.conversation_memory import ConversationMemory
from amancore.sales.discovery import DiscoveryEngine
from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService
from amancore.sales.qualification import QualificationEngine
from amancore.services.events import EventDispatcher
from amancore.skills.objection_handling import ObjectionHandlingSkill
from tests.common import TempDirTestCase, make_brain, make_db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def build_agent(brain, crm, dispatcher):
    return SalesAgent(
        brain, crm,
        ConversationMemory(crm),
        DiscoveryEngine(),
        QualificationEngine(),
        ObjectionHandlingSkill(brain),
        FollowupEngine(),
        HandoffService(dispatcher),
        router=None, dispatcher=dispatcher,
    )


class SalesEval(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.agent = build_agent(self.brain, self.crm, self.dispatcher)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_sales_scenarios(self):
        scenarios = json.loads((FIXTURES / "sales_scenarios.json").read_text())["scenarios"]
        for sc in scenarios:
            lid = self.crm.create_lead(
                company=sc["lead"]["company"],
                market=sc["lead"].get("market"),
                industry=sc["lead"].get("industry"),
                language=sc["lead"].get("language"),
            )
            lead = self.crm.get_lead(lid)
            result = None
            for msg in sc["messages"]:
                result = self.agent.process_message(lead, msg)
            exp = sc["expect"]
            if "final_state" in exp:
                self.assertEqual(result["state"], exp["final_state"], sc["id"])
            if exp.get("opportunity_created"):
                self.assertTrue(result.get("opportunity_id"), sc["id"])
            if "objection" in exp:
                self.assertEqual(result.get("objection"), exp["objection"], sc["id"])
            if exp.get("needs_human"):
                self.assertTrue(result.get("needs_human"), sc["id"])
            if "state" in exp:
                self.assertEqual(result["state"], exp["state"], sc["id"])


if __name__ == "__main__":
    unittest.main()
