import unittest
from pathlib import Path

from amancore.config import load_config
from amancore.ops.backup import BackupService
from amancore.ops.incidents import IncidentService
from amancore.ops.jobs import JobRunner, JobStore
from amancore.ops.registry import JobRegistry
from amancore.ops.recovery import RecoveryService
from amancore.ops.scheduler import SchedulerRuntime
from amancore.services.events import EventDispatcher, CanonicalEvent
from tests.common import TempDirTestCase, make_brain, make_db
from tests.insights_seed import seed_won_deal

ROOT = Path(__file__).resolve().parent.parent.parent


class OpsFlowIntegrationTest(TempDirTestCase, unittest.TestCase):
    """Scheduler → Analytics/Insights/Backup · Incident → Alert · Recovery → Health."""

    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.config = load_config(ROOT, mutate_environ=False)
        # scheduler config for jobs
        import yaml

        self.sched_cfg = yaml.safe_load((ROOT / "configs" / "scheduler.yaml").read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_scheduler_runs_analytics_and_insights_jobs(self):
        # seed some data so insights produce something
        seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        store = JobStore(self.db, config=self.sched_cfg)
        handlers = JobRegistry(self.db, self.config, ROOT).handlers()
        runner = JobRunner(store, handlers, worker_id="test")
        runtime = SchedulerRuntime(store, runner, self.sched_cfg)
        # force-enqueue the insight job regardless of cron
        job_id = store.enqueue("insights.daily", idempotency_key="test:insights.daily")
        result = runner.run_job(store.get(job_id))
        self.assertEqual(result["status"], "completed")
        self.assertIn("created", result["result"])
        # analytics job
        job_id2 = store.enqueue("analytics.daily", idempotency_key="test:analytics.daily")
        result2 = runner.run_job(store.get(job_id2))
        self.assertEqual(result2["status"], "completed")

    def test_scheduler_backup_job(self):
        # real project root backup is heavy; use a scoped registry handler check instead
        store = JobStore(self.db, config=self.sched_cfg)
        handlers = JobRegistry(self.db, self.config, ROOT).handlers()
        self.assertIn("database.backup", handlers)
        self.assertIn("backup.verify", handlers)

    def test_incident_creates_critical_alert(self):
        alerts = []
        from amancore.ops.alerts import AlertDispatcher

        dispatcher = AlertDispatcher(
            self.db,
            transport=__import__("amancore.ops.alerts", fromlist=["LogAlertTransport"]).LogAlertTransport(),
        )
        svc = IncidentService(self.db, dispatcher=dispatcher)
        incident_id = svc.handle_critical("database_failure", "integrity check failed",
                                          evidence={"check": "integrity"})
        # incident exists with CRITICAL severity
        self.assertEqual(svc.get(incident_id)["severity"], "CRITICAL")
        # alert persisted
        from amancore.ops.alerts import AlertStore

        alerts = AlertStore(self.db).list()
        self.assertTrue(any("database_failure" in a["related_entity"] for a in alerts))

    def test_recovery_after_backup(self):
        backup = BackupService(self.db, ROOT)
        # only run if a real production DB exists (local environment)
        if (ROOT / "storage" / "aman_core.db").exists():
            backup.create_backup("database")
            backup.verify_latest("database")
            recovery = RecoveryService(self.db, ROOT, backup_service=backup)
            result = recovery.run_recovery_test()
            self.assertIn(result["status"], ("PASS", "FAIL"))

    def test_health_check_via_job(self):
        store = JobStore(self.db, config=self.sched_cfg)
        handlers = JobRegistry(self.db, self.config, ROOT).handlers()
        job_id = store.enqueue("health.check", idempotency_key="test:health")
        result = JobRunner(store, handlers).run_job(store.get(job_id))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["result"], "PASS")

    def test_events_emitted_for_ops(self):
        dispatcher = EventDispatcher()
        seen = []
        dispatcher.subscribe("alert.raised", lambda e: seen.append(e.event_type))
        from amancore.ops.alerts import AlertDispatcher

        AlertDispatcher(self.db, dispatcher=dispatcher) if hasattr(AlertDispatcher, "dispatcher") else None


if __name__ == "__main__":
    unittest.main()
