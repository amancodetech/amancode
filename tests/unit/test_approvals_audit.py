import unittest

from amancore.errors import ApprovalError
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from tests.common import TempDirTestCase, make_db


class ApprovalAuditTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.audit = AuditService(self.db)
        self.approvals = ApprovalService(self.db, audit=self.audit)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_approval_lifecycle(self):
        aid = self.approvals.create_approval_request(
            "price", "owner", "high", "final price", {"amount": 100}, "decision_policies.price_approval"
        )
        self.assertEqual(self.approvals.get(aid)["status"], "pending")
        self.approvals.approve(aid, "owner")
        self.assertEqual(self.approvals.get(aid)["status"], "approved")

    def test_reject(self):
        aid = self.approvals.create_approval_request("price", "owner", "high", "r")
        self.approvals.reject(aid, "owner", "too high")
        self.assertEqual(self.approvals.get(aid)["status"], "rejected")

    def test_expire(self):
        aid = self.approvals.create_approval_request("price", "owner", "high", "r")
        self.approvals.expire(aid)
        self.assertEqual(self.approvals.get(aid)["status"], "expired")

    def test_approve_non_pending_raises(self):
        aid = self.approvals.create_approval_request("price", "owner", "high", "r")
        self.approvals.approve(aid, "owner")
        with self.assertRaises(ApprovalError):
            self.approvals.approve(aid, "owner")

    def test_audit_append_and_query(self):
        self.audit.record(action="test.action", resource="r", result="ok", correlation_id="c1")
        self.assertEqual(self.audit.count(), 1)
        self.assertEqual(len(self.audit.query(correlation_id="c1")), 1)
        # approval actions are also audited
        aid = self.approvals.create_approval_request("price", "owner", "high", "r")
        self.assertGreaterEqual(self.audit.count(), 2)


if __name__ == "__main__":
    unittest.main()
