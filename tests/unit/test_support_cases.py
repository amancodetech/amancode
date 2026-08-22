import unittest

from amancore.errors import NotFoundError
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_db


class SupportCaseStoreTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = SupportCaseStore(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_create_get(self):
        cid = self.store.create("billing", priority="HIGH", summary="want refund")
        case = self.store.get(cid)
        self.assertEqual(case["category"], "billing")
        self.assertEqual(case["priority"], "HIGH")
        self.assertEqual(case["status"], "open")
        self.assertEqual(case["escalated"], 0)

    def test_invalid_priority(self):
        with self.assertRaises(ValueError):
            self.store.create("general", priority="URGENT")

    def test_list_filters(self):
        self.store.create("billing", priority="HIGH")
        self.store.create("technical_support", priority="LOW")
        self.assertEqual(len(self.store.list(category="billing")), 1)
        self.assertEqual(len(self.store.list(priority="LOW")), 1)
        self.assertEqual(len(self.store.list(status="open")), 2)

    def test_status_lifecycle(self):
        cid = self.store.create("general")
        self.store.set_status(cid, "in_progress")
        self.store.set_status(cid, "resolved")
        case = self.store.get(cid)
        self.assertEqual(case["status"], "resolved")
        self.assertIsNotNone(case["resolved_at"])
        # reopen
        self.store.set_status(cid, "open")
        self.assertIsNotNone(self.store.get(cid)["reopened_at"])

    def test_invalid_status(self):
        cid = self.store.create("general")
        with self.assertRaises(ValueError):
            self.store.set_status(cid, "weird")

    def test_escalate(self):
        cid = self.store.create("legal", priority="HIGH")
        self.store.escalate(cid, owner="owner")
        case = self.store.get(cid)
        self.assertEqual(case["escalated"], 1)
        self.assertEqual(case["status"], "waiting_owner")
        self.assertEqual(case["owner"], "owner")

    def test_update_missing_raises(self):
        with self.assertRaises(NotFoundError):
            self.store.update("nope", summary="x")

    def test_counts(self):
        self.store.create("billing")
        self.store.create("legal")
        self.store.set_status(self.store.list()[-1]["case_id"], "resolved")
        counts = self.store.counts()
        self.assertEqual(sum(counts.values()), 2)


if __name__ == "__main__":
    unittest.main()
