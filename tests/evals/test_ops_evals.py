"""Phase 3H evals — 12 operational scenarios (spec section 50)."""

import json
import unittest
from pathlib import Path

from amancore.errors import ProductionNotEnabledError
from amancore.ops.alerts import AlertDispatcher, AlertStore, LogAlertTransport
from amancore.ops.incidents import IncidentService
from amancore.ops.jobs import JobRunner, JobStore
from amancore.production.gate import ProductionGateService
from tests.common import TempDirTestCase, make_db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class OpsEvals(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _job_store(self):
        return JobStore(self.db, config={"retry": {"max_attempts": 2, "backoff_seconds": 1,
                                                   "backoff_factor": 2, "timeout_seconds": 5}})

    def test_ops_scenarios(self):
        scenarios = json.loads((FIXTURES / "ops_scenarios.json").read_text())["scenarios"]
        for sc in scenarios:
            sid = sc["id"]
            with self.subTest(sid=sid):
                self._run_scenario(sid)

    def _run_scenario(self, sid: str):
        if sid == "daily_insights_job":
            store = self._job_store()
            jid = store.enqueue("insights.daily", idempotency_key="ev:insights")
            result = JobRunner(store, {"insights.daily": lambda p: {"created": 0}}).run_job(store.get(jid))
            self.assertEqual(result["status"], "completed", sid)

        elif sid == "failed_job_retry_dead":
            store = self._job_store()

            def boom(p):
                raise ConnectionError("provider down")  # retryable error

            jid = store.enqueue("job.x")
            runner = JobRunner(store, {"job.x": boom})
            first = runner.run_job(store.get(jid))          # attempt 1 -> queued (retry)
            second = runner.run_job(store.get(jid))         # attempt 2 -> dead (max 2)
            self.assertEqual(first["status"], "queued", sid)
            self.assertEqual(second["status"], "dead", sid)
            self.assertEqual(store.counts().get("dead"), 1, sid)

        elif sid == "backup":
            from amancore.ops.backup import BackupService

            proj = self.tmp / "proj"
            (proj / "storage").mkdir(parents=True)
            import sqlite3

            conn = sqlite3.connect(proj / "storage" / "aman_core.db")
            conn.execute("CREATE TABLE t (x)")
            conn.commit()
            conn.close()
            svc = BackupService(self.db, proj)
            created = svc.create_backup("database")
            backup_id = created["kinds"]["database"]["artifacts"][0]["backup_id"]
            verified = svc.verify_backup(backup_id)
            self.assertEqual(verified["status"], "verified", sid)
            self.assertTrue(verified["checks"]["checksum"], sid)
            self.assertEqual(verified["checks"]["integrity"], "ok", sid)

        elif sid == "restore_test":
            from amancore.ops.backup import BackupService
            from amancore.ops.recovery import RecoveryService

            proj = self.tmp / f"proj-{sid}"      # unique per scenario
            (proj / "storage").mkdir(parents=True)
            from amancore.storage.db import open_database

            open_database(proj / "storage" / "aman_core.db",
                          Path(__file__).resolve().parent.parent.parent / "amancore" / "storage" / "schema.sql").close()
            svc = BackupService(self.db, proj)
            svc.create_backup("database")
            svc.verify_latest("database")
            result = RecoveryService(self.db, proj, backup_service=svc).run_recovery_test()
            self.assertEqual(result["status"], "PASS", sid)

        elif sid == "owner_alert":
            dispatcher = AlertDispatcher(self.db, transport=LogAlertTransport())
            result = dispatcher.dispatch(severity="HIGH", title="test alert",
                                         summary="delivery check", related_entity="ev")
            self.assertTrue(result["delivered"], sid)

        elif sid == "duplicate_alert":
            dispatcher = AlertDispatcher(self.db, transport=LogAlertTransport())
            dispatcher.dispatch(severity="HIGH", title="x", fingerprint="dup:1")
            second = dispatcher.dispatch(severity="HIGH", title="x", fingerprint="dup:1")
            self.assertTrue(second["deduplicated"], sid)
            dup_rows = self.db.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE dedup_key = 'dup:1'"
            ).fetchone()["c"]
            self.assertEqual(dup_rows, 1, sid)

        elif sid == "production_disabled":
            from amancore.channels.whatsapp import WhatsAppAdapter

            adapter = WhatsAppAdapter({"mode": "production", "production_enabled": False,
                                       "phone_number_id": "1"})
            adapter.provider.access_token = "EA-fake"
            with self.assertRaises(ProductionNotEnabledError):
                adapter.send("5511", "text", "hi")

        elif sid == "whatsapp_verification_missing":
            cfg = {"environment": {"mode": "mock", "production_enabled": False, "webhook_url": ""},
                   "official_verification": {"status": "OFFICIAL_VERIFICATION_PENDING"}}
            report = ProductionGateService(cfg, db=self.db, env={}).check()
            self.assertEqual(report["verdict"], "NOT_READY", sid)
            self.assertEqual(report["official_verification_status"], "OFFICIAL_VERIFICATION_PENDING", sid)

        elif sid == "human_active":
            from amancore.crm.service import CRMService

            crm = CRMService(self.db)
            lead_id = crm.create_lead(contact_whatsapp="5511")
            from amancore.channels.handover import HandoverService

            HandoverService(crm).activate_human(lead_id)
            self.assertFalse(HandoverService(crm).can_send_ai(lead_id), sid)

        elif sid == "security_incident":
            dispatcher = AlertDispatcher(self.db, transport=LogAlertTransport())
            svc = IncidentService(self.db, dispatcher=dispatcher)
            blocked = []
            iid = svc.handle_critical("security_incident", "breach", block_action=lambda: blocked.append(1))
            self.assertTrue(blocked, sid)
            self.assertEqual(svc.get(iid)["severity"], "CRITICAL", sid)
            alerts = AlertStore(self.db).list()
            self.assertTrue(any(a["severity"] == "CRITICAL" for a in alerts), sid)

        elif sid == "retention":
            from amancore.ops.retention import RetentionService

            svc = RetentionService(self.db, config={"lead_inactive_days": 1})
            self.db.execute(
                "INSERT INTO leads (lead_id, status, lead_stage, created_at, updated_at) "
                "VALUES ('old', 'new', 'nurture', '2000-01-01', '2000-01-01')"
            )
            self.db.execute(
                "INSERT INTO leads (lead_id, status, lead_stage, created_at, updated_at) "
                "VALUES ('protected', 'new', 'hot', ?, ?)",
                (__import__("amancore.ids", fromlist=["utcnow"]).utcnow(),
                 __import__("amancore.ids", fromlist=["utcnow"]).utcnow()),
            )
            self.db.commit()
            result = svc.run()
            self.assertEqual(result["leads_removed"], 1, sid)
            remaining = {r["lead_id"] for r in self.db.execute("SELECT lead_id FROM leads").fetchall()}
            self.assertIn("protected", remaining, sid)
            self.assertEqual(result["audit"], "permanent (never deleted)", sid)

        elif sid == "startup":
            from amancore.ops.startup import StartupService

            service = StartupService(Path(__file__).resolve().parent.parent.parent, db=self.db)
            result = service.check()
            self.assertTrue(result["ok"], sid)
            self.assertTrue(result["production_send_blocked"], sid)


if __name__ == "__main__":
    unittest.main()
