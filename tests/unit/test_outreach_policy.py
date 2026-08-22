import unittest

from amancore.services.outreach_policy import (
    ALLOW,
    APPROVAL_REQUIRED,
    DENY,
    OutreachPolicy,
)
from tests.common import TempDirTestCase, make_brain


class OutreachPolicyTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.policy = OutreachPolicy(make_brain(self.tmp), rate_limit=20)

    def test_allow(self):
        d = self.policy.evaluate(
            {"company": "Acme", "website": "acme.co.id", "market": "indonesia", "industry": "trading"}
        )
        self.assertEqual(d.action, ALLOW)

    def test_deny_opt_out(self):
        d = self.policy.evaluate({"company": "Acme", "opt_out": 1})
        self.assertEqual(d.action, DENY)

    def test_deny_unsupported_market(self):
        d = self.policy.evaluate({"company": "Acme", "website": "a.co", "market": "france"})
        self.assertEqual(d.action, DENY)

    def test_deny_no_presence(self):
        d = self.policy.evaluate({"name": "X"})
        self.assertEqual(d.action, DENY)

    def test_deny_already_contacted(self):
        d = self.policy.evaluate(
            {"company": "Acme", "website": "acme.co.id", "market": "indonesia", "industry": "trading"},
            previous_contact=True,
        )
        self.assertEqual(d.action, DENY)

    def test_deny_rate_limit(self):
        d = self.policy.evaluate(
            {"company": "Acme", "website": "acme.co.id", "market": "indonesia", "industry": "trading"},
            sent_today=20,
        )
        self.assertEqual(d.action, DENY)

    def test_approval_required_no_personalization(self):
        d = self.policy.evaluate({"company": "Acme", "website": "acme.co.id", "market": "indonesia"})
        self.assertEqual(d.action, APPROVAL_REQUIRED)


if __name__ == "__main__":
    unittest.main()
