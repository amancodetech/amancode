import unittest

from amancore.services.policy import (
    ALLOW,
    APPROVAL_REQUIRED,
    ESCALATE,
    PolicyEngine,
)
from amancore.services.risk import RiskEngine
from tests.common import TempDirTestCase, make_brain


class RiskTest(unittest.TestCase):
    def setUp(self):
        self.risk = RiskEngine()

    def test_classify_levels(self):
        self.assertEqual(self.risk.classify("price.calculated"), "high")
        self.assertEqual(self.risk.classify("lead.created"), "low")
        self.assertEqual(self.risk.classify("message.sent"), "medium")

    def test_action_overrides(self):
        self.assertEqual(self.risk.classify("deal.won", action="contract"), "critical")
        self.assertEqual(self.risk.classify("lead.created", action="discount"), "high")


class PolicyTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        _, self.brain = self.store.current()
        self.policy = PolicyEngine()

    def test_low_allows(self):
        d = self.policy.evaluate(self.brain, "lead.created", "low")
        self.assertEqual(d.action, ALLOW)

    def test_high_requires_approval(self):
        d = self.policy.evaluate(self.brain, "price.calculated", "high")
        self.assertEqual(d.action, APPROVAL_REQUIRED)

    def test_critical_escalates(self):
        d = self.policy.evaluate(self.brain, "deal.won", "critical")
        self.assertEqual(d.action, ESCALATE)

    def test_final_price_requires_approval(self):
        d = self.policy.evaluate(self.brain, "lead.updated", "low", action="final_price")
        self.assertEqual(d.action, APPROVAL_REQUIRED)

    def test_refund_escalates(self):
        d = self.policy.evaluate(self.brain, "lead.updated", "low", action="refund")
        self.assertEqual(d.action, ESCALATE)


if __name__ == "__main__":
    unittest.main()
