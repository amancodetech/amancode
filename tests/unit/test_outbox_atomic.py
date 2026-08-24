"""OUT-202: atomic outbox claims + stale reclaim (kills C1 duplicate sends, C4 stranded rows).

Also documents WHY claim_mode=legacy is broken (deterministic race proof).
"""

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.ids import utcnow  # noqa: E402
from amancore.storage.db import Database, ensure_columns  # noqa: E402


class RecordingAdapter:
    def __init__(self, fail_first_for: set | None = None):
        self.sent: list[str] = []
        self._lock = threading.Lock()
        self.fail_first_for = fail_first_for or set()

    def send(self, recipient, message_type, payload):
        with self._lock:
            self.sent.append(recipient)
        return {"provider_message_id": f"pmid-{len(self.sent)}"}


class Harness(unittest.TestCase):
    def setUp(self):
        self.db = Database(ROOT / "storage" / "_test_outbox202.db")
        from amancore.storage.db import _split_schema

        schema = (ROOT / "amancore" / "storage" / "schema.sql").read_text()
        tables_sql, _ = _split_schema(schema)
        self.db.apply_schema(tables_sql)
        ensure_columns(self.db)
        self.db.execute("DELETE FROM message_outbox")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        (ROOT / "storage" / "_test_outbox202.db").unlink(missing_ok=True)

    def make(self, n=5):
        outbox = MessageOutbox(self.db)
        for i in range(n):
            outbox.enqueue("whatsapp", f"+9000000000{i}", "text", {"body": f"m{i}"},
                           idempotency_key=f"ik{i}")
        return outbox

    def worker(self, adapter, mode):
        class P:
            def evaluate_send(self, *a, **k):
                return "allow"

        return OutboxWorker(MessageOutbox(self.db), {"whatsapp": adapter}, P(),
                            claim_mode=mode)


class OutboxAtomicTests(Harness):
    def test_legacy_mode_race_documented(self):
        """next_ready() has no ownership → same message processed twice."""
        self.make(3)
        a1, a2 = RecordingAdapter(), RecordingAdapter()
        snap1 = MessageOutbox(self.db).next_ready(10)   # worker A snapshot
        snap2 = MessageOutbox(self.db).next_ready(10)   # worker B same snapshot
        w1 = self.worker(a1, "legacy"); w2 = self.worker(a2, "legacy")
        for m in snap1:
            w1.process_one(m)
        for m in snap2:
            w2.process_one(m)
        self.assertEqual(len(a1.sent), 3)
        self.assertEqual(len(a2.sent), 3)               # ← the C1 bug, proven

    def test_atomic_concurrent_no_duplicates(self):
        self.make(20)
        adapter = RecordingAdapter()

        def run():
            try:
                self.worker(adapter, "atomic").drain(limit=25)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        errors: list[Exception] = []
        threads = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(adapter.sent), 20)          # exactly once each
        self.assertEqual(len(set(adapter.sent)), 20)

    def test_atomic_single_thread_drains_all_once(self):
        self.make(7)
        adapter = RecordingAdapter()
        r1 = self.worker(adapter, "atomic").drain(limit=10)
        r2 = self.worker(adapter, "atomic").drain(limit=10)
        self.assertEqual(len([x for x in r1 if x["status"] == "sent"]), 7)
        self.assertEqual(r2, [])

    def test_stale_processing_reclaimed(self):
        outbox = self.make(2)
        mid = outbox.next_ready(1)[0]["message_id"]
        outbox.mark_processing(mid)
        old = "2000-01-01T00:00:00+00:00"
        self.db.execute("UPDATE message_outbox SET claimed_at=? WHERE message_id=?", (old, mid))
        self.db.commit()
        got = self.worker(RecordingAdapter(), "atomic").drain(limit=10)
        self.assertEqual(len(got), 2)
        row = outbox.get(mid)
        self.assertEqual(row["status"], "sent")          # revived and delivered
        self.assertIn("stale-reclaimed", row["failure_reason"])

    def test_fresh_processing_not_stolen(self):
        outbox = self.make(2)
        mid = outbox.next_ready(1)[0]["message_id"]
        outbox.mark_processing(mid)
        self.db.execute("UPDATE message_outbox SET claimed_at=? WHERE message_id=?", (utcnow(), mid))
        self.db.commit()
        results = self.worker(RecordingAdapter(), "atomic").drain(limit=10)
        self.assertEqual(len(results), 1)                # only the queued one
        self.assertEqual(outbox.get(mid)["status"], "processing")

    def test_unknown_claim_mode_rejected(self):
        with self.assertRaises(ValueError):
            self.worker(RecordingAdapter(), "yolo")

    def test_migration_columns_idempotent(self):
        ensure_columns(self.db); ensure_columns(self.db)   # twice → no error
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(message_outbox)").fetchall()}
        self.assertLessEqual({"claimed_at", "claim_token"}, cols)


if __name__ == "__main__":
    unittest.main()
