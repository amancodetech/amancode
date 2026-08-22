import unittest

from amancore.crm.service import CRMService
from amancore.sales.conversation_memory import (
    ConversationMemory,
    extract_facts,
)
from tests.common import TempDirTestCase, make_db


class ConversationMemoryTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.crm = CRMService(self.db)
        self.mem = ConversationMemory(self.crm)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_get_or_create(self):
        lid = self.crm.create_lead(company="Acme")
        m = self.mem.get_or_create(lid, language="id")
        self.assertEqual(m["current_state"], "new")
        self.assertEqual(m["language"], "id")
        self.assertEqual(m["facts"], {})

    def test_merge_facts_and_conflict(self):
        lid = self.crm.create_lead(company="Acme")
        m = self.mem.get_or_create(lid)
        m = self.mem.merge_facts(m, {"budget": "$5000"})
        self.assertEqual(m["facts"]["budget"], "$5000")
        # conflicting fact → flag
        m = self.mem.merge_facts(m, {"budget": "$100"})
        self.assertIn("clarify budget", m["open_questions"])

    def test_save_persists(self):
        lid = self.crm.create_lead(company="Acme")
        m = self.mem.get_or_create(lid)
        m = self.mem.merge_facts(m, {"authority": "owner"})
        m["current_state"] = "discovery"
        self.mem.save(m)
        reloaded = self.mem.get_or_create(lid)
        self.assertEqual(reloaded["facts"]["authority"], "owner")
        self.assertEqual(reloaded["current_state"], "discovery")

    def test_extract_facts_deterministic(self):
        facts = extract_facts("I am the owner and my budget is $5000, need it in 2 weeks", router=None)
        self.assertIn("authority", facts)
        self.assertEqual(facts["budget"], "$5000")
        self.assertIn("timeline", facts)

    def test_extract_facts_problem(self):
        facts = extract_facts("I need an online ordering system", router=None)
        self.assertEqual(facts["problem"], "stated")


if __name__ == "__main__":
    unittest.main()
