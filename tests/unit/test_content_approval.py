import unittest

from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from amancore.services.content_approval import ContentApprovalService
from tests.common import TempDirTestCase, make_brain, make_db


class ContentApprovalTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.approvals = ApprovalService(self.db, audit=AuditService(self.db))
        self.svc = ContentApprovalService(self.brain, approvals=self.approvals)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_low_educational_approved(self):
        d = self.svc.evaluate({"content_id": "c", "body": "Here are 3 practical tips to improve your business"})
        self.assertEqual(d["status"], "approved")

    def test_forbidden_rejected(self):
        d = self.svc.evaluate({"content_id": "c", "body": "We guarantee revenue growth"})
        self.assertEqual(d["status"], "rejected")

    def test_commercial_review(self):
        d = self.svc.evaluate({"content_id": "c", "body": "We offer web application services for growing businesses"})
        self.assertEqual(d["status"], "review")
        self.assertFalse(d["needs_owner"])

    def test_pricing_requires_owner(self):
        d = self.svc.evaluate({"content_id": "c", "body": "Our pricing starts at $1000 for a full website"})
        self.assertEqual(d["status"], "review")
        self.assertTrue(d["needs_owner"])
        self.assertIsNotNone(d["approval_id"])

    def test_risk_classification(self):
        self.assertEqual(self.svc.classify_risk("general tips about running a business"), "low")
        self.assertEqual(self.svc.classify_risk("we offer our service"), "medium")
        self.assertEqual(self.svc.classify_risk("our pricing $100"), "high")
        self.assertEqual(self.svc.classify_risk("legal advice"), "critical")


if __name__ == "__main__":
    unittest.main()
