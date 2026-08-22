import unittest

from amancore.crm.service import CRMService
from amancore.errors import NotFoundError
from tests.common import TempDirTestCase, make_db


class CRMTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.crm = CRMService(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_lead_lifecycle(self):
        lid = self.crm.create_lead(name="Acme", company="Acme Trading", market="indonesia")
        lead = self.crm.get_lead(lid)
        self.assertEqual(lead["name"], "Acme")
        self.crm.update_lead(lid, lead_stage="qualified", lead_score=55)
        self.assertEqual(self.crm.get_lead(lid)["lead_stage"], "qualified")

    def test_search_leads(self):
        self.crm.create_lead(name="Alpha", company="Alpha Co")
        self.crm.create_lead(name="Beta", company="Beta Co", lead_stage="qualified")
        self.assertEqual(len(self.crm.search_leads(query="Alpha")), 1)
        self.assertEqual(len(self.crm.search_leads(stage="qualified")), 1)

    def test_update_missing_lead_raises(self):
        with self.assertRaises(NotFoundError):
            self.crm.update_lead("nonexistent", name="x")

    def test_full_entity_chain(self):
        lid = self.crm.create_lead(name="Owner", company="Co")
        cid = self.crm.create_customer(company="Co", market="gcc")
        self.crm.update_customer(cid, language="ar")
        oid = self.crm.create_opportunity(lid, service="website_system", estimated_value=2000)
        self.crm.update_opportunity(oid, stage="qualified")
        pid = self.crm.create_project(cid, service="website_system")
        self.crm.update_project(pid, status="active")
        cpid = self.crm.create_care_plan(cid, plan_tier="standard", price=150)
        conv = self.crm.append_conversation(lid, channel="whatsapp", facts='{"need":"website"}')
        self.assertIsNotNone(self.crm.get_customer(cid))
        self.assertIsNotNone(self.crm.get_conversation(conv))
        self.assertIsNotNone(cpid)


if __name__ == "__main__":
    unittest.main()
