"""JOBS-304: cooperative cancel (CC1), real follow-ups (CC2), business
timezone + catchup (CC5), retention activity guards (D8)."""

import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone as tz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.ops.jobs import JobCancelled, JobRunner, JobStore  # noqa: E402
from amancore.ops.retention import RetentionService  # noqa: E402
from amancore.ops.scheduler import SchedulerRuntime, cron_matches  # noqa: E402
from amancore.storage.db import Database, ensure_columns  # noqa: E402
from amancore.storage.db import _split_schema  # noqa: E402


class Harness(unittest.TestCase):
    def setUp(self):
        from tests._db import fresh_db, wipe

        self.db = fresh_db()
        wipe(self.db)

    def tearDown(self):
        self.db.close()


class CC1CooperativeCancel(Harness):
    def test_timeout_signals_cancel_event(self):
        store = JobStore(self.db)
        aborted = {"flag": False}

        def handler(payload):
            ev = payload.get("_cancel_event")
            for _ in range(250):                 # ~5s max, checked every 20ms
                if ev is not None and ev.is_set():
                    aborted["flag"] = True       # clean checkpoint exit
                    raise JobCancelled("aborting cleanly")
                time.sleep(0.02)
            return {"done": True}

        runner = JobRunner(store, {"t.slow": handler}, timeout_seconds=0.15)
        store.enqueue("t.slow", idempotency_key="j-slow")
        result = runner.run_due()[0]
        self.assertTrue(aborted["flag"], "cancel event must reach the handler")
        self.assertIn("timeout", result["error"])

    def test_live_zombie_lease_not_requeued(self):
        import threading as th

        store = JobStore(self.db)
        blocker = th.Event()

        def handler(payload):
            blocker.wait(10)
            return {}

        runner = JobRunner(store, {"t.z": handler}, timeout_seconds=0.05)
        store.enqueue("t.z", idempotency_key="j-zombie")
        claimed = store.claim_next("worker-test")     # → status=running + lease
        real_job_id = claimed[0]["job_id"]
        self.db.execute(
            "UPDATE jobs SET locked_until='2000-01-01'")
        self.db.commit()

        # simulate the survived-grace worker thread (still alive)
        ghost = th.Thread(target=lambda: blocker.wait(10), daemon=True)
        ghost.start()
        runner._zombies[real_job_id] = ghost

        # scheduler.tick passes these live-zombie ids as exclusions
        self.assertEqual(
            store.requeue_expired_leases(exclude_job_ids=runner.zombie_job_ids()), 0,
            "live zombie's expired lease must stay held")
        blocker.set(); ghost.join(1)
        self.assertEqual(runner.zombie_job_ids(), set(), "dead zombie unregisters")
        self.assertEqual(store.requeue_expired_leases(), 1,
                         "once the zombie dies, the lease frees")


class CC2RealFollowups(Harness):
    def _registry_followups(self):
        from amancore.ops.registry import JobRegistry

        cfg = type("C", (), {"retention": {}, "database_path": "x",
                             "app": {"compliance": {"approved_templates":
                                     {"followup": {"name": "f1", "language": "ar"}}}}})()
        return JobRegistry(self.db, config=cfg, root=ROOT).handlers()["followups.check"]

    def _seed_lead(self, lead_id="L1", due=True, wa="+905321112233", opt_out=0,
                   consent=True):
        now = datetime.now(tz.utc)
        nxt = (now - timedelta(days=1)).isoformat() if due else (now + timedelta(days=9)).isoformat()
        self.db.execute(
            "INSERT INTO leads (lead_id, lead_stage, name, contact_whatsapp, opt_out,"
            " next_followup_at, consent_at, created_at, updated_at)"
            " VALUES (?, 'nurture', 'Test', ?, ?, ?, ?, ?, ?)",
            (lead_id, wa, opt_out, nxt,
             now.isoformat() if consent else None, now.isoformat(), now.isoformat()))
        self.db.execute(
            "INSERT INTO conversations (conversation_id, lead_id, mode, created_at, updated_at)"
            " VALUES (?, ?, 'AI_ACTIVE', ?, ?)",
            (f"c-{lead_id}", lead_id, now.isoformat(), now.isoformat()))
        self.db.commit()

    def test_due_lead_gets_real_outbox_message_and_cursor_advances(self):
        self._seed_lead()
        followups = self._registry_followups()
        res = followups({})
        self.assertEqual(res["enqueued"], 1)
        row = self.db.execute(
            "SELECT idempotency_key, recipient FROM message_outbox"
            " WHERE idempotency_key LIKE 'followup:L1:%'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["recipient"], "905321112233")     # normalized W2
        nxt = self.db.execute(
            "SELECT next_followup_at FROM leads WHERE lead_id='L1'").fetchone()[0]
        self.assertGreater(nxt, datetime.now(tz.utc).isoformat())   # advanced +3d

    def test_second_run_same_day_no_duplicate(self):
        self._seed_lead()
        followups = self._registry_followups()
        r1 = followups({})
        r2 = followups({})
        self.assertEqual(r1["enqueued"], 1)
        self.assertEqual(r2["enqueued"], 0)                    # idempotent per day

    def test_human_mode_lead_skipped(self):
        self._seed_lead(lead_id="L2")
        self.db.execute("UPDATE conversations SET mode='HUMAN_ACTIVE' WHERE lead_id='L2'")
        self.db.commit()
        res = self._registry_followups()({})
        self.assertEqual(res["enqueued"], 0)


class CC5TimezoneCatchup(Harness):
    def test_business_timezone_honored(self):
        rt = SchedulerRuntime(JobStore(self.db), None,
                              {"timezone": "Asia/Makassar", "jobs": {}})
        # Makassar = UTC+8 → local 14:00 is UTC 06:00
        utc_noon = datetime(2026, 8, 24, 6, 0, tzinfo=tz.utc)
        self.assertTrue(cron_matches("0 14 * * *", utc_noon.astimezone(rt.tz)))
        self.assertFalse(cron_matches("0 14 * * *", utc_noon))

    def test_catchup_backfills_missed_slot_once(self):
        cfg = {"timezone": "UTC",
               "catchup_minutes": 60,
               "jobs": {"nightly": {"enabled": True, "cron": "0 3 * * *"}}}
        rt = SchedulerRuntime(JobStore(self.db), None, cfg)
        # scheduler last ticked at 02:29, died, restarts at 03:00:
        rt._last_tick = datetime(2026, 8, 24, 2, 29, tzinfo=tz.utc)
        now = datetime(2026, 8, 24, 3, 0, tzinfo=tz.utc)
        res = rt.tick(now=now)
        # missed 03:00 slot fires now; the 02:29→now sweep adds nothing extra
        self.assertEqual(len(res["enqueued"]), 1)
        # second tick one minute later: no duplicate for the same slot
        res2 = rt.tick(now=now + timedelta(minutes=1))
        self.assertEqual(len([e for e in res2["enqueued"] if "nightly" in e]), 0)

    def test_healthy_everyminute_cron_fires_once_per_tick(self):
        cfg = {"timezone": "UTC", "catchup_minutes": 60,
               "jobs": {"pulse": {"enabled": True, "cron": "* * * * *"}}}
        rt = SchedulerRuntime(JobStore(self.db), None, cfg)
        t0 = datetime(2026, 8, 24, 9, 0, tzinfo=tz.utc)
        r1 = rt.tick(now=t0)
        self.assertEqual(len(r1["enqueued"]), 1)               # first tick: current slot only
        r2 = rt.tick(now=t0 + timedelta(minutes=1))
        self.assertEqual(len(r2["enqueued"]), 1)               # next minute: exactly one more
        r3 = rt.tick(now=t0 + timedelta(minutes=4))            # 3-minute gap → backfill 3
        self.assertEqual(len(r3["enqueued"]), 3)


class D8RetentionGuards(Harness):
    def _seed(self, lead_id, last_msg_iso):
        now = datetime(2026, 1, 1, tzinfo=tz.utc).isoformat()  # created long ago
        self.db.execute(
            "INSERT INTO leads (lead_id, lead_stage, created_at, updated_at) VALUES (?, 'nurture', ?, ?)",
            (lead_id, now, now))
        self.db.execute(
            "INSERT INTO conversations (conversation_id, lead_id, mode, created_at,"
            " updated_at, last_message_at) VALUES (?, ?, 'AI_ACTIVE', ?, ?, ?)",
            (f"c-{lead_id}", lead_id, now, now, last_msg_iso))
        self.db.commit()

    def test_recently_active_lead_survives_created_cutoff(self):
        self._seed("active", datetime(2026, 8, 20, tzinfo=tz.utc).isoformat())
        svc = RetentionService(self.db, config={})
        svc.run()
        row = self.db.execute("SELECT 1 FROM leads WHERE lead_id='active'").fetchone()
        self.assertIsNotNone(row, "recently-active nurture lead must survive")

    def test_stale_conversation_deleted_by_last_activity_not_creation(self):
        # created long ago BUT talked recently → conversation survives D8 fix
        self._seed("talker", datetime(2026, 8, 22, tzinfo=tz.utc).isoformat())
        RetentionService(self.db, config={}).run()
        row = self.db.execute(
            "SELECT 1 FROM conversations WHERE conversation_id='c-talker'").fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
