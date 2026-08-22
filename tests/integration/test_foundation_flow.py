import unittest

from amancore.business_brain.store import BrainStore
from amancore.crm.service import CRMService
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from amancore.services.events import CanonicalEvent, EventDispatcher
from amancore.services.policy import PolicyEngine
from amancore.services.risk import RiskEngine
from tests.common import TempDirTestCase, make_brain, make_db


class FoundationFlowTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = make_brain(self.tmp)
        self.audit = AuditService(self.db)
        self.crm = CRMService(self.db)
        self.approvals = ApprovalService(self.db, audit=self.audit)
        self.dispatcher = EventDispatcher()
        self.risk = RiskEngine()
        self.policy = PolicyEngine()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_full_foundation_chain(self):
        _, brain = self.store.current()

        # lead -> event
        lead_id = self.crm.create_lead(name="R", company="R Co", market="indonesia")
        seen = []
        self.dispatcher.subscribe("lead.created", seen.append)
        self.dispatcher.publish(
            CanonicalEvent(
                event_id="e1", event_type="lead.created", timestamp="t",
                correlation_id="c1", payload={"lead_id": lead_id},
            )
        )
        self.assertEqual(len(seen), 1)

        # risk -> policy
        risk = self.risk.classify("price.calculated")
        decision = self.policy.evaluate(brain, "price.calculated", risk)
        self.assertEqual(decision.action, "approval_required")

        # approval -> audit
        aid = self.approvals.create_approval_request(
            "price", "owner", risk, "final price", policy_reference=decision.policy_reference
        )
        self.approvals.approve(aid, "owner")

        self.assertGreaterEqual(self.audit.count(), 2)


if __name__ == "__main__":
    unittest.main()
