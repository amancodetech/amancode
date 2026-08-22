import unittest

from amancore.content.service import ContentService
from tests.common import TempDirTestCase, make_db


class ContentServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.svc = ContentService(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_create_and_get(self):
        cid = self.svc.create(topic="X", title="X", body="hello")
        content = self.svc.get(cid)
        self.assertEqual(content["status"], "draft")
        self.assertTrue(content["content_hash"])

    def test_duplicate_detection(self):
        self.svc.create(topic="Digital transformation", angle="A", hook="H", body="B")
        dups = self.svc.find_duplicate(topic="Digital transformation", angle="A", hook="H", body="B")
        self.assertEqual(len(dups), 1)

    def test_different_content_not_duplicate(self):
        self.svc.create(topic="Digital transformation", angle="A", hook="H", body="B")
        self.assertEqual(
            len(self.svc.find_duplicate(topic="Totally different", angle="Z", hook="Y", body="X")),
            0,
        )

    def test_update(self):
        cid = self.svc.create(topic="X", body="b")
        self.svc.update(cid, status="approved")
        self.assertEqual(self.svc.get(cid)["status"], "approved")


if __name__ == "__main__":
    unittest.main()
