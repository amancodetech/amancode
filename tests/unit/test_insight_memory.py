import unittest

from amancore.insights.memory import InsightMemory
from amancore.insights.model import new_insight, new_recommendation
from tests.common import TempDirTestCase, make_db


def _insight(**kw):
    defaults = dict(
        type_="trend", category="sales", title="T", summary="S",
        evidence={"metric": "m", "value": 1, "sample_size": 5},
        confidence="HIGH", severity="LOW", fingerprint="fp:1",
    )
    defaults.update(kw)
    return new_insight(**defaults)


class InsightMemoryTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.mem = InsightMemory(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_save_and_get(self):
        saved, updated = self.mem.save_insight(_insight())
        self.assertFalse(updated)
        self.assertEqual(self.mem.get_insight(saved["insight_id"])["title"], "T")

    def test_dedup_updates_not_duplicates(self):
        self.mem.save_insight(_insight())
        second, updated = self.mem.save_insight(_insight(summary="Updated summary"))
        self.assertTrue(updated)
        rows = self.mem.list_insights()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["summary"], "Updated summary")

    def test_different_fingerprint_new_insight(self):
        self.mem.save_insight(_insight(fingerprint="a"))
        self.mem.save_insight(_insight(fingerprint="b"))
        self.assertEqual(len(self.mem.list_insights()), 2)

    def test_expire_and_supersede(self):
        saved, _ = self.mem.save_insight(_insight(fingerprint="x"))
        self.mem.expire(saved["insight_id"])
        self.assertEqual(self.mem.get_insight(saved["insight_id"])["status"], "expired")
        # expired insight no longer blocks a new one with same fingerprint
        saved2, updated = self.mem.save_insight(_insight(fingerprint="x"))
        self.assertFalse(updated)
        self.assertEqual(len(self.mem.list_insights()), 2)

    def test_expire_stale(self):
        saved, _ = self.mem.save_insight(_insight(expires_at="2000-01-01T00:00:00+00:00"))
        n = self.mem.expire_stale()
        self.assertEqual(n, 1)
        self.assertEqual(self.mem.get_insight(saved["insight_id"])["status"], "expired")

    def test_recommendation_crud(self):
        saved, _ = self.mem.save_insight(_insight())
        rec = new_recommendation(
            insight_id=saved["insight_id"], type_="observe", title="R", problem="P",
            evidence_ids=[saved["insight_id"]], proposed_action="A", alternatives=[],
            expected_benefit="B", expected_risk="R", dependencies="", confidence="HIGH",
            requires_owner_approval=False,
        )
        rid = self.mem.save_recommendation(rec)
        got = self.mem.get_recommendation(rid)
        self.assertEqual(got["type"], "observe")
        self.mem.update_recommendation(rid, status="accepted")
        self.assertEqual(self.mem.get_recommendation(rid)["status"], "accepted")

    def test_decision_log(self):
        did = self.mem.record_decision("recommendation", "r1", "accepted", "owner", "ok")
        rows = self.mem.list_decisions("r1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "accepted")
        self.assertEqual(rows[0]["decision_id"], did)


if __name__ == "__main__":
    unittest.main()
