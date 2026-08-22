import unittest

from amancore.ops.jobs import JobRunner, JobStore
from amancore.ops.scheduler import SchedulerRuntime, cron_matches
from tests.common import TempDirTestCase, make_db

CFG = {
    "scheduler": {"lease_seconds": 300, "poll_interval_seconds": 1},
    "retry": {"max_attempts": 3, "backoff_seconds": 1, "backoff_factor": 2, "timeout_seconds": 5},
    "jobs": {
        "analytics.daily": {"enabled": True, "cron": "* * * * *"},
        "research.daily": {"enabled": False, "cron": "* * * * *"},
    },
}


class JobStoreTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = JobStore(self.db, config=CFG)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_enqueue_get(self):
        jid = self.store.enqueue("analytics.daily", {"period": "daily"})
        job = self.store.get(jid)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["payload"]["period"], "daily")

    def test_idempotency_no_duplicate(self):
        jid1 = self.store.enqueue("analytics.daily", idempotency_key="slot-1")
        jid2 = self.store.enqueue("analytics.daily", idempotency_key="slot-1")
        self.assertEqual(jid1, jid2)
        self.assertEqual(len(self.store.list(type_="analytics.daily")), 1)

    def test_claim_lease(self):
        jid = self.store.enqueue("analytics.daily")
        self.assertTrue(self.store.claim(jid, "worker-1"))
        job = self.store.get(jid)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["locked_by"], "worker-1")
        # second claim fails while leased
        self.assertFalse(self.store.claim(jid, "worker-2"))

    def test_expired_lease_reclaimable(self):
        jid = self.store.enqueue("analytics.daily")
        self.store.claim(jid, "worker-1", lease_seconds=-1)  # already expired
        reclaimed = self.store.requeue_expired_leases()
        self.assertEqual(reclaimed, 1)
        self.assertEqual(self.store.get(jid)["status"], "queued")
        self.assertTrue(self.store.claim(jid, "worker-2"))

    def test_retry_then_dead(self):
        jid = self.store.enqueue("analytics.daily")
        # attempt 1 -> queued with backoff
        self.assertEqual(self.store.fail(jid, "boom", retryable=True), "queued")
        job = self.store.get(jid)
        self.assertEqual(job["attempts"], 1)
        self.assertIsNotNone(job["next_attempt_at"])
        # attempts 2,3 -> dead after max_attempts
        self.store.fail(jid, "boom", retryable=True)
        self.assertEqual(self.store.fail(jid, "boom", retryable=True), "dead")
        self.assertEqual(self.store.get(jid)["status"], "dead")

    def test_non_retryable_immediate_dead(self):
        jid = self.store.enqueue("analytics.daily")
        self.assertEqual(self.store.fail(jid, "no handler", retryable=False), "dead")

    def test_claim_next_due_only(self):
        jid1 = self.store.enqueue("analytics.daily")  # due now
        jid2 = self.store.enqueue("analytics.daily", run_at="2999-01-01T00:00:00+00:00")  # future
        claimed = self.store.claim_next("worker-1")
        self.assertEqual([j["job_id"] for j in claimed], [jid1])
        self.assertEqual(self.store.get(jid2)["status"], "queued")

    def test_counts(self):
        self.store.enqueue("analytics.daily")
        self.assertEqual(self.store.counts().get("queued"), 1)


class JobRunnerTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = JobStore(self.db, config=CFG)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_success(self):
        jid = self.store.enqueue("job.a")
        runner = JobRunner(self.store, {"job.a": lambda p: {"ok": 1}})
        result = runner.run_job(self.store.get(jid))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.store.get(jid)["status"], "completed")

    def test_no_handler_dead(self):
        jid = self.store.enqueue("nope")
        result = JobRunner(self.store, {}).run_job(self.store.get(jid))
        self.assertEqual(result["status"], "dead")
        self.assertEqual(result["error"], "no handler for job type nope")

    def test_retryable_failure(self):
        def boom(payload):
            raise ConnectionError("down")

        jid = self.store.enqueue("job.b")
        result = JobRunner(self.store, {"job.b": boom}).run_job(self.store.get(jid))
        self.assertEqual(result["status"], "queued")  # retried
        self.assertEqual(self.store.get(jid)["attempts"], 1)

    def test_timeout(self):
        import time

        def slow(payload):
            time.sleep(2)

        jid = self.store.enqueue("job.c")
        runner = JobRunner(self.store, {"job.c": slow}, timeout_seconds=1)
        result = runner.run_job(self.store.get(jid))
        self.assertIn(result["status"], ("queued", "dead"))
        self.assertIn("timeout", result["error"].lower())


class CronTest(unittest.TestCase):
    def test_every_minute(self):
        self.assertTrue(cron_matches("* * * * *"))

    def test_exact_match(self):
        from datetime import datetime, timezone

        now = datetime(2026, 8, 22, 6, 30, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("30 6 * * *", now))
        self.assertFalse(cron_matches("31 6 * * *", now))

    def test_step(self):
        from datetime import datetime, timezone

        now = datetime(2026, 8, 22, 6, 30, tzinfo=timezone.utc)
        self.assertTrue(cron_matches("*/30 * * * *", now))
        other = datetime(2026, 8, 22, 6, 37, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("*/15 * * * *", other))

    def test_weekly_monday(self):
        from datetime import datetime, timezone

        monday = datetime(2026, 8, 24, 6, 30, tzinfo=timezone.utc)  # Monday
        self.assertTrue(cron_matches("30 6 * * 0", monday))  # dow 0 = Monday
        sunday = datetime(2026, 8, 23, 6, 30, tzinfo=timezone.utc)
        self.assertFalse(cron_matches("30 6 * * 0", sunday))


class SchedulerRuntimeTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = JobStore(self.db, config=CFG)
        self.runner = JobRunner(self.store, {"analytics.daily": lambda p: {"ok": 1}})
        self.runtime = SchedulerRuntime(self.store, self.runner, CFG)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_due_job_types_respects_enabled(self):
        due = self.runtime.due_job_types()
        self.assertIn("analytics.daily", due)
        # disabled jobs are due per cron but SKIPPED by tick
        self.assertIn("research.daily", self.runtime.tick()["skipped_disabled"])

    def test_tick_enqueues_due(self):
        summary = self.runtime.tick()
        self.assertTrue(any("analytics.daily" in e for e in summary["enqueued"]))
        # second tick same slot -> idempotent (no duplicate)
        summary2 = self.runtime.tick()
        self.assertEqual(len(self.store.list(type_="analytics.daily")), 1)

    def test_run_once_executes(self):
        result = self.runtime.run_once()
        self.assertEqual(result["completed"], 1)


if __name__ == "__main__":
    unittest.main()
