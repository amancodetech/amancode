import unittest
from pathlib import Path

from amancore.ops.incidents import IncidentService
from amancore.ops.retention import RetentionService
from tests.common import TempDirTestCase, make_db


class IncidentServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.alerts = []
        self.svc = IncidentService(
            self.db, owner_alert=lambda lvl, msg, corr, **kw: self.alerts.append((lvl, msg)),
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_create_get(self):
        iid = self.svc.create("job_failure", "MEDIUM", component="scheduler",
                              description="job x failed")
        inc = self.svc.get(iid)
        self.assertEqual(inc["status"], "open")
        self.assertEqual(inc["type"], "job_failure")

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            self.svc.create("weird", "LOW")

    def test_status_lifecycle(self):
        iid = self.svc.create("ai_failure", "HIGH")
        self.svc.set_status(iid, "investigating")
        self.svc.set_status(iid, "mitigated", note="switched provider")
        self.svc.set_status(iid, "resolved")
        inc = self.svc.get(iid)
        self.assertEqual(inc["status"], "resolved")
        self.assertIsNotNone(inc["resolved_at"])
        self.assertIn("switched provider", inc["action_taken"])

    def test_handle_critical_flow(self):
        blocked = []
        iid = self.svc.handle_critical(
            "security_incident", "possible breach",
            evidence={"source": "alert"}, component="auth",
            block_action=lambda: blocked.append(True),
        )
        self.assertTrue(blocked)  # dangerous action blocked
        inc = self.svc.get(iid)
        self.assertEqual(inc["severity"], "CRITICAL")
        self.assertTrue(any(lvl == "critical" for lvl, _ in self.alerts))
        self.assertEqual(self.svc.list(status="open")[0]["incident_id"], iid)

    def test_list_filters(self):
        self.svc.create("webhook_failure", "MEDIUM")
        self.svc.create("database_failure", "CRITICAL")
        self.assertEqual(len(self.svc.list()), 2)
        self.assertEqual(len(self.svc.list(severity="CRITICAL")), 1)


class RetentionServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.svc = RetentionService(self.db, config={
            "lead_inactive_days": 365, "conversation_active_days": 90,
            "audit_retention": "permanent", "business_brain_versions": "permanent",
            "content_days": 180,
        })

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _old_lead(self, lead_id="l-old"):
        self.db.execute(
            "INSERT INTO leads (lead_id, status, lead_stage, created_at, updated_at) "
            "VALUES (?, 'new', 'nurture', '2000-01-01T00:00:00+00:00', '2000-01-01T00:00:00+00:00')",
            (lead_id,),
        )
        self.db.commit()

    def test_removes_old_nurture_leads(self):
        self._old_lead()
        self._old_lead("l-old2")
        # a fresh lead must survive
        self.db.execute(
            "INSERT INTO leads (lead_id, status, lead_stage, created_at, updated_at) "
            "VALUES ('l-new', 'new', 'nurture', ?, ?)",
            (__import__("amancore.ids", fromlist=["utcnow"]).utcnow(),
             __import__("amancore.ids", fromlist=["utcnow"]).utcnow()),
        )
        self.db.commit()
        result = self.svc.run()
        self.assertEqual(result["leads_removed"], 2)
        rows = self.db.execute("SELECT lead_id FROM leads").fetchall()
        self.assertEqual([r["lead_id"] for r in rows], ["l-new"])

    def test_protects_lead_with_opportunity(self):
        self._old_lead()
        self.db.execute(
            "INSERT INTO opportunities (opportunity_id, lead_id, service, created_at, updated_at) "
            "VALUES ('o1', 'l-old', 'website_standard', ?, ?)",
            (__import__("amancore.ids", fromlist=["utcnow"]).utcnow(),
             __import__("amancore.ids", fromlist=["utcnow"]).utcnow()),
        )
        self.db.commit()
        result = self.svc.run()
        self.assertEqual(result["leads_removed"], 0)
        self.assertIsNotNone(self.db.execute("SELECT lead_id FROM leads WHERE lead_id='l-old'").fetchone())

    def test_protects_active_support_case(self):
        self._old_lead()
        self.db.execute(
            "INSERT INTO support_cases (case_id, lead_id, category, priority, status, created_at, updated_at) "
            "VALUES ('c1', 'l-old', 'technical_support', 'MEDIUM', 'open', ?, ?)",
            (__import__("amancore.ids", fromlist=["utcnow"]).utcnow(),
             __import__("amancore.ids", fromlist=["utcnow"]).utcnow()),
        )
        self.db.commit()
        result = self.svc.run()
        self.assertEqual(result["leads_removed"], 0)

    def test_removes_old_draft_content_only(self):
        self.db.execute(
            "INSERT INTO content_items (content_id, status, created_at, updated_at) "
            "VALUES ('c-draft', 'draft', '2000-01-01', '2000-01-01')"
        )
        self.db.execute(
            "INSERT INTO content_items (content_id, status, created_at, updated_at) "
            "VALUES ('c-approved', 'approved', '2000-01-01', '2000-01-01')"
        )
        self.db.commit()
        result = self.svc.run()
        self.assertEqual(result["content_removed"], 1)
        rows = {r["content_id"] for r in self.db.execute("SELECT content_id FROM content_items").fetchall()}
        self.assertEqual(rows, {"c-approved"})

    def test_audit_permanent(self):
        result = self.svc.run()
        self.assertEqual(result["audit"], "permanent (never deleted)")
        self.assertEqual(result["business_brain_versions"], "permanent (never deleted)")


if __name__ == "__main__":
    unittest.main()
