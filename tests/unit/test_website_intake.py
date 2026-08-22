import unittest

from amancore.channels.website import WebsiteLeadIntake
from amancore.crm.service import CRMService
from amancore.services.events import EventDispatcher
from tests.common import TempDirTestCase, make_db


class WebsiteIntakeTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.intake = WebsiteLeadIntake(self.crm, self.db, {
            "intake_rate_per_ip_minute": 2,
            "intake_rate_per_email_day": 2,
        }, dispatcher=self.dispatcher)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _payload(self, email="a@example.com"):
        return {"name": "Ahmed", "email": email, "message": "I want a website", "consent": True}

    def test_valid_submit(self):
        r = self.intake.submit(self._payload(), ip="1.1.1.1")
        self.assertEqual(r["status"], "created")
        lead = self.crm.get_lead(r["lead_id"])
        self.assertEqual(lead["contact_email"], "a@example.com")
        self.assertEqual(lead["source_channel"], "website")

    def test_rejects_without_consent(self):
        r = self.intake.submit({**self._payload(), "consent": False})
        self.assertEqual(r["status"], "rejected")

    def test_rejects_invalid_email(self):
        r = self.intake.submit({**self._payload(), "email": "nope"})
        self.assertEqual(r["status"], "rejected")

    def test_rate_limit(self):
        self.intake.submit(self._payload("r@example.com"), ip="2.2.2.2")
        self.intake.submit(self._payload("r2@example.com"), ip="2.2.2.2")
        r = self.intake.submit(self._payload("r3@example.com"), ip="2.2.2.2")
        self.assertEqual(r["status"], "rejected")

    def test_sanitizes_html(self):
        r = self.intake.submit({**self._payload("x@example.com"), "message": "<script>alert(1)</script> hello"}, ip="3.3.3.3")
        lead = self.crm.get_lead(r["lead_id"])
        self.assertNotIn("<script>", lead["need"])


if __name__ == "__main__":
    unittest.main()
