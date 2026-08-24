"""OUT-203/204/205: inbound idempotency hard gate (C2), monotonic delivery
status (C3), dead-letter never silent (visibility).

Completes the Outbox cluster started by OUT-202.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.channels.webhook_server import make_status_recorder  # noqa: E402
from amancore.storage.db import (  # noqa: E402
    Database, ensure_columns, ensure_unique_indexes,
)


class ClusterHarness(unittest.TestCase):
    def setUp(self):
        self.db = Database(ROOT / "storage" / "_test_outbox_cluster.db")
        from amancore.storage.db import _split_schema

        schema = (ROOT / "amancore" / "storage" / "schema.sql").read_text()
        tables_sql, index_sql = _split_schema(schema)
        self.db.apply_schema(tables_sql)
        ensure_columns(self.db)
        ensure_unique_indexes(self.db)
        self.db.execute("DELETE FROM channel_messages")
        self.db.execute("DELETE FROM message_outbox")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        (ROOT / "storage" / "_test_outbox_cluster.db").unlink(missing_ok=True)


class Out203InboundIdempotency(ClusterHarness):
    def test_unique_index_rejects_duplicate_wamid(self):
        self.db.execute(
            "INSERT INTO channel_messages (direction, wa_id, wa_message_id, body, status, created_at)"
            " VALUES ('in', 'W1', 'wamid-X', 'hello', '', datetime('now'))"
        )
        self.db.commit()
        with self.assertRaises(Exception):
            self.db.execute(
                "INSERT INTO channel_messages (direction, wa_id, wa_message_id, body, status, created_at)"
                " VALUES ('in', 'W1', 'wamid-X', 'hello AGAIN', '', datetime('now'))"
            )

    def test_dedupe_keeps_original_then_index_applies(self):
        self.db.execute("DROP INDEX IF EXISTS uq_channel_messages_wamid")
        for body in ("first", "dup", "dup2"):
            self.db.execute(
                "INSERT INTO channel_messages (direction, wa_id, wa_message_id, body, status, created_at)"
                " VALUES ('in', 'W1', 'wamid-D', ?, '', datetime('now'))", (body,))
        self.db.commit()
        ensure_unique_indexes(self.db)   # legacy DB: clean + create without error
        n = self.db.execute(
            "SELECT COUNT(*) c FROM channel_messages WHERE wa_message_id='wamid-D'"
        ).fetchone()["c"]
        body = self.db.execute(
            "SELECT body FROM channel_messages WHERE wa_message_id='wamid-D'"
        ).fetchone()["body"]
        self.assertEqual(n, 1)
        self.assertEqual(body, "first")  # lowest rowid survives

    def test_null_wamid_rows_unlimited(self):
        for i in range(3):
            self.db.execute(
                "INSERT INTO channel_messages (direction, wa_id, wa_message_id, body, status, created_at)"
                " VALUES ('in', 'W1', NULL, ?, '', datetime('now'))", (f"m{i}",))
        self.db.commit()
        ensure_unique_indexes(self.db)
        n = self.db.execute("SELECT COUNT(*) c FROM channel_messages").fetchone()["c"]
        self.assertEqual(n, 3)


class Out204MonotonicStatus(ClusterHarness):
    def recorder(self):
        return make_status_recorder(self.db)

    def seed(self):
        ob = MessageOutbox(self.db)
        mid = ob.enqueue("whatsapp", "+905000000001", "text", {"body": "hi"})
        ob.mark_processing(mid)
        ob.mark_sent(mid, provider_message_id="pmid-777")
        return mid

    def test_forward_progress_ok(self):
        self.seed()
        r = self.recorder()("pmid-777", "delivered")
        self.assertTrue(r["updated"])
        r2 = self.recorder()("pmid-777", "read")
        self.assertTrue(r2["updated"])

    def test_out_of_order_never_downgrades(self):
        self.seed()
        rec = self.recorder()
        rec("pmid-777", "read")                      # jump to read first
        stale = rec("pmid-777", "delivered")         # older receipt arrives late
        self.assertFalse(stale["updated"])
        self.assertIn("stale", stale["reason"])
        row = self.db.execute(
            "SELECT status FROM message_outbox WHERE provider_message_id='pmid-777'"
        ).fetchone()
        self.assertEqual(row["status"], "read")

    def test_unknown_provider_id_reported_not_silent(self):
        r = self.recorder()("pmid-does-not-exist", "delivered")
        self.assertFalse(r["updated"])
        self.assertEqual(r["reason"], "unknown id")


class Out205DeadLetter(ClusterHarness):
    def worker_with_alert(self, max_attempts=2):
        class P:
            def evaluate_send(self, *a, **k):
                return "allow"

        class BoomAdapter:
            def send(self, *a, **k):
                raise RuntimeError("provider down")

        alert = MagicMock()
        w = OutboxWorker(MessageOutbox(self.db, max_attempts=max_attempts),
                         {"whatsapp": BoomAdapter()}, P(),
                         claim_mode="atomic", owner_alert=alert)
        return w, alert

    def test_dead_letter_fires_fingerprinted_alert(self):
        ob = MessageOutbox(self.db, max_attempts=2)
        mid = ob.enqueue("whatsapp", "+905000000002", "text", {"body": "x"})
        w, alert = self.worker_with_alert(max_attempts=2)
        w.drain(limit=5)                              # attempt 1 → queued retry
        self.assertEqual(alert.call_count, 0)         # not dead yet
        self.db.execute("UPDATE message_outbox SET next_attempt_at='2000-01-01'")
        self.db.commit()
        w.drain(limit=5)                              # attempt 2 → DEAD
        self.assertEqual(alert.call_count, 1)
        args, kwargs = alert.call_args
        self.assertEqual(args[0], "HIGH")
        self.assertEqual(kwargs["event_type"], "outbox.dead")
        self.assertEqual(kwargs["resource"], mid)
        self.assertEqual(ob.get(mid)["status"], "dead")

    def test_failure_reason_clamped_200(self):
        ob = MessageOutbox(self.db, max_attempts=1)
        mid = ob.enqueue("whatsapp", "+905000000003", "text", {"body": "x"})
        ob.mark_failed(mid, "x" * 5000)
        reason = ob.get(mid)["failure_reason"]
        self.assertLessEqual(len(reason), 200)


if __name__ == "__main__":
    unittest.main()
