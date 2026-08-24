import unittest
from pathlib import Path

import yaml

from amancore.agents.support import SupportAgent
from amancore.channels.handover import HandoverService
from amancore.crm.service import CRMService
from amancore.services.events import EventDispatcher
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_brain, make_db

ROOT = Path(__file__).resolve().parent.parent.parent
SUPPORT_YAML = ROOT / "configs" / "support.yaml"


def build_agent(db, brain, crm, dispatcher, owner_alert=None, support_policy=None):
    cases = SupportCaseStore(db)
    support_agent = SupportAgent(
        brain, crm, cases, HandoverService(crm, dispatcher),
        owner_alert=owner_alert, support_policy=support_policy,
        audit=None, dispatcher=dispatcher,
    )
    return support_agent, cases


class SupportAgentTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.alerts = []
        self.policy = yaml.safe_load(SUPPORT_YAML.read_text(encoding="utf-8"))
        self.agent, self.cases = build_agent(
            self.db, self.brain, self.crm, self.dispatcher,
            owner_alert=lambda lvl, msg, corr, **kw: self.alerts.append((lvl, msg)),
            support_policy=self.policy,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _lead(self, wa_id="5511"):
        return self.crm.get_lead(self.crm.create_lead(contact_whatsapp=wa_id, name="Test"))

    def _customer_lead(self, wa_id="5511", company="Co"):
        lead = self._lead(wa_id)
        opp = self.crm.get_opportunity(self.crm.create_opportunity(lead["lead_id"], "website_standard"))
        cust = self.crm.won_opportunity(opp["opportunity_id"], company)
        customer = self.crm.get_customer(cust["customer_id"])
        self.crm.update_project(cust["project_id"], status="in_progress", milestones='["design done","build"]', timeline="4 weeks")
        return lead, customer

    def test_project_status_from_stored_data(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "how is my project going?", customer)
        self.assertEqual(result["category"], "project_status")
        self.assertIn("in_progress", result["reply"])
        self.assertIn("Milestones", result["reply"])

    def test_billing_refund_escalates_to_owner(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "I want a refund please", customer)
        self.assertEqual(result["category"], "billing")
        self.assertTrue(result["escalated"])
        case = self.cases.get(result["case_id"])
        self.assertEqual(case["escalated"], 1)
        self.assertEqual(case["status"], "waiting_owner")
        self.assertIn("owner", result["reply"].lower())
        self.assertIn("HUMAN_REQUESTED", self.agent.handover.get_mode(lead["lead_id"]))
        self.assertTrue(any(lvl == "high" for lvl, _ in self.alerts))

    def test_legal_escalates(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "I will sue you for breach of contract", customer)
        self.assertEqual(result["category"], "legal")
        self.assertTrue(result["escalated"])
        self.assertIn("legal review", result["reply"].lower())

    def test_complaint_escalates(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "this is a complaint, I am furious", customer)
        self.assertEqual(result["category"], "complaint")
        self.assertTrue(result["escalated"])
        case = self.cases.get(result["case_id"])
        self.assertEqual(case["priority"], "HIGH")

    def test_scope_change_escalates(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "can you change the scope of my project?", customer)
        self.assertTrue(result["escalated"])

    def test_critical_security_incident(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "there is a security incident, my data is breached!", customer)
        self.assertEqual(result["priority"], "CRITICAL")
        self.assertTrue(result["escalated"])
        self.assertTrue(any(lvl == "critical" for lvl, _ in self.alerts))
        case = self.cases.get(result["case_id"])
        self.assertEqual(case["priority"], "CRITICAL")

    def test_human_request_handoff(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "I want to talk to a human", customer)
        self.assertTrue(result["handoff"])
        self.assertEqual(self.agent.handover.get_mode(lead["lead_id"]), "HUMAN_REQUESTED")

    def test_feature_request_logged(self):
        lead, customer = self._customer_lead()
        result = self.agent.process_message(lead, "can you add a new feature to my site?", customer)
        self.assertEqual(result["category"], "feature_request")
        self.assertFalse(result.get("escalated"))
        self.assertIsNotNone(result["case_id"])

    def test_unknown_policy_escalates(self):
        lead, customer = self._customer_lead()
        agent2, _ = build_agent(
            self.db, self.brain, self.crm, self.dispatcher,
            owner_alert=lambda lvl, msg, corr, **kw: self.alerts.append((lvl, msg)),
            support_policy={},  # empty policy -> UNKNOWN_POLICY
        )
        result = agent2.process_message(lead, "can you add a new feature?", customer)
        self.assertFalse(result.get("escalated"))  # case created normally...
        # but UNKNOWN_POLICY must alert the owner
        self.assertTrue(any("UNKNOWN_POLICY" in msg for _, msg in self.alerts))

    def test_no_refund_authority(self):
        self.assertFalse(hasattr(self.agent, "refund"))
        self.assertFalse(hasattr(self.agent, "apply_discount"))
        self.assertFalse(hasattr(self.agent, "change_price"))
        self.assertFalse(hasattr(self.agent, "change_scope"))
        self.assertFalse(hasattr(self.agent, "write_business_brain"))

    def test_response_filter(self):
        self.assertFalse(self.agent.safe_reply("internal notes and lead score leaked")["allowed"])
        self.assertTrue(self.agent.safe_reply("your project is in progress")["allowed"])

    def test_reuses_open_case(self):
        lead, customer = self._customer_lead()
        r1 = self.agent.process_message(lead, "my site has an error 500", customer)
        r2 = self.agent.process_message(lead, "my site has an error 502 now", customer)
        self.assertEqual(r1["case_id"], r2["case_id"])


if __name__ == "__main__":
    unittest.main()
