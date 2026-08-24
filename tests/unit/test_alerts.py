import unittest
from pathlib import Path

import yaml

from amancore.analytics.alerts import AlertService
from amancore.ids import utcnow
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_db

ALERTS_YAML = Path(__file__).resolve().parent.parent.parent / "configs" / "alerts.yaml"


class AlertServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.alerts = []
        config = yaml.safe_load(ALERTS_YAML.read_text(encoding="utf-8"))
        self.svc = AlertService(
            self.db,
            config=config,
            owner_alert=lambda lvl, msg, corr, **kw: self.alerts.append((lvl, msg)),
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_no_alerts_when_clean(self):
        self.assertEqual(self.svc.check_all(), [])

    def test_dead_letter_growth(self):
        for i in range(3):
            self.db.execute(
                "INSERT INTO message_outbox (message_id, channel, status, created_at) VALUES (?, 'whatsapp', 'dead', ?)",
                (f"m{i}", utcnow()),
            )
        self.db.commit()
        found = [a for a in self.svc.check_all() if a["alert"] == "dead_letter_growth"]
        self.assertEqual(len(found), 1)

    def test_critical_support_alert(self):
        store = SupportCaseStore(self.db)
        store.create("legal", priority="CRITICAL")
        found = [a for a in self.svc.check_all() if a["alert"] == "critical_support"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "critical")
        self.assertTrue(any(lvl == "critical" for lvl, _ in self.alerts))

    def test_hot_lead_waiting(self):
        from amancore.crm.service import CRMService

        crm = CRMService(self.db)
        crm.create_lead(lead_stage="hot", next_followup_at="2000-01-01T00:00:00+00:00")
        found = [a for a in self.svc.check_all() if a["alert"] == "hot_lead_waiting"]
        self.assertEqual(len(found), 1)

    def test_stale_case(self):
        store = SupportCaseStore(self.db)
        cid = store.create("technical_support")
        self.db.execute(
            "UPDATE support_cases SET updated_at = ? WHERE case_id = ?",
            ("2000-01-01T00:00:00+00:00", cid),
        )
        self.db.commit()
        found = [a for a in self.svc.check_all() if a["alert"] == "stale_case"]
        self.assertEqual(len(found), 1)

    def test_api_failures(self):
        self.db.execute(
            "INSERT INTO usage_records (request_id, provider, model, task_class, status, created_at) "
            "VALUES ('r1', 'p', 'm', 'routine', 'error', ?), ('r2', 'p', 'm', 'routine', 'error', ?), "
            "('r3', 'p', 'm', 'routine', 'error', ?)",
            (utcnow(), utcnow(), utcnow()),
        )
        self.db.commit()
        found = [a for a in self.svc.check_all() if a["alert"] == "api_failures"]
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
