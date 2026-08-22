import unittest

from amancore.channels.handover import HandoverService
from amancore.crm.service import CRMService
from tests.common import TempDirTestCase, make_db


class HandoverTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.crm = CRMService(self.db)
        self.svc = HandoverService(self.crm)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _lead(self):
        return self.crm.create_lead(company="Co")

    def test_default_ai_active(self):
        lid = self._lead()
        self.assertEqual(self.svc.get_mode(lid), "AI_ACTIVE")
        self.assertTrue(self.svc.can_send_ai(lid))

    def test_human_activation_blocks_ai(self):
        lid = self._lead()
        self.svc.request_human(lid)
        self.assertEqual(self.svc.get_mode(lid), "HUMAN_REQUESTED")
        self.svc.activate_human(lid)
        self.assertEqual(self.svc.get_mode(lid), "HUMAN_ACTIVE")
        self.assertFalse(self.svc.can_send_ai(lid))

    def test_resume_ai(self):
        lid = self._lead()
        self.svc.activate_human(lid)
        self.svc.resume_ai(lid)
        self.assertEqual(self.svc.get_mode(lid), "AI_RESUMED")
        self.assertTrue(self.svc.can_send_ai(lid))


if __name__ == "__main__":
    unittest.main()
