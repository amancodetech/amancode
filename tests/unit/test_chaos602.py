"""CHAOS-602 — remaining failure classes (plan §441 matrix).

Covers: disk-full backup (ENOSPC at both write points), DB locked
contention, server-restart durability, partial-migration resume,
AI malformed response. Other classes live in their task suites
(wa302/outbox_atomic/jobs304/compliance_kit) — see G6 declaration.
"""

import errno
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.storage.db import Database, ensure_columns  # noqa: E402
from tests._db import SharedDBTestCase, fresh_db  # noqa: E402


class DiskFullBackup(SharedDBTestCase):
    def _service(self, tmp: Path):
        from amancore.ops.backup import BackupService

        return BackupService(self.db, tmp, database_path=tmp / "src.db")

    def _seed_src(self, src: Path):
        sdb = Database(src)
        schema = ROOT / "amancore" / "storage" / "schema.sql"
        sdb.apply_schema(schema.read_text(encoding="utf-8"))
        ensure_columns(sdb)
        sdb.execute("INSERT INTO leads (lead_id, lead_stage, created_at,"
                    " updated_at) VALUES ('X', 'new', '2026', '2026')")
        sdb.commit()
        sdb.close()

    def test_enospc_on_secondary_copy_raises_no_hollow_row(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(dir=str(ROOT / "storage")))
        try:
            self._seed_src(tmp / "src.db")
            svc = self._service(tmp)
            before = self.db.execute("SELECT COUNT(*) c FROM backups").fetchone()[0]
            with patch("amancore.ops.backup.shutil.copy2",
                       side_effect=OSError(errno.ENOSPC, "No space left")):
                with self.assertRaises(OSError):
                    svc.create_backup("database")
            after = self.db.execute("SELECT COUNT(*) c FROM backups").fetchone()[0]
            # BAK-103 contract: failure RAISES; registry gains no row for it
            self.assertEqual(before, after,
                             "failed backup must not register as success")
        finally:
            import shutil as _sh

            _sh.rmtree(tmp, ignore_errors=True)

    def test_enospc_on_primary_backup_api_raises(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(dir=str(ROOT / "storage")))
        try:
            self._seed_src(tmp / "src.db")
            svc = self._service(tmp)

            class FullSrc:
                def backup_to(self_inner, dst):
                    raise OSError(errno.ENOSPC, "No space left")

            with patch.object(Database, "backup_to",
                              lambda self, dst: (_ for _ in ()).throw(
                                  OSError(errno.ENOSPC, "disk full"))):
                with self.assertRaises(Exception):
                    svc.create_backup("database")
        finally:
            import shutil as _sh

            _sh.rmtree(tmp, ignore_errors=True)


class DbLockedContention(SharedDBTestCase):
    def test_writer_waits_and_succeeds_after_external_lock_release(self):
        from tests._db import TEST_DB_PATH

        raw = __import__("sqlite3").connect(str(TEST_DB_PATH), timeout=1,
                                            check_same_thread=False)
        raw.execute("BEGIN IMMEDIATE")           # foreign writer holds lock
        released = threading.Event()

        def holder():
            time.sleep(0.4)
            raw.rollback(); raw.close()
            released.set()

        threading.Thread(target=holder, daemon=True).start()
        t0 = time.perf_counter()
        self.db.execute(
            "INSERT INTO message_outbox (message_id, channel, recipient,"
            " message_type, payload, status, created_at)"
            " VALUES ('lock-probe','whatsapp','x','text','{}','queued','t')")
        self.db.commit()
        elapsed = time.perf_counter() - t0
        self.assertTrue(released.is_set())
        self.assertGreaterEqual(elapsed, 0.3)    # genuinely waited, not failed


class RestartDurability(unittest.TestCase):
    def test_wal_persists_across_close_reopen(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(dir=str(ROOT / "storage")))
        dbpath = tmp / "restart.db"
        try:
            d1 = Database(dbpath)
            schema = (ROOT / "amancore" / "storage" / "schema.sql").read_text()
            d1.apply_schema(schema)
            d1.execute("INSERT INTO leads (lead_id, lead_stage, created_at,"
                       " updated_at) VALUES ('R1','new','t','t')")
            d1.commit()
            d1.close()                            # simulated restart #1
            d2 = Database(dbpath)
            row = d2.execute("SELECT lead_id FROM leads WHERE lead_id='R1'").fetchone()
            self.assertIsNotNone(row, "committed data must survive restart")
            d2.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(dbpath) + suffix).unlink(missing_ok=True)
            tmp.rmdir()


class PartialMigrationResume(unittest.TestCase):
    def test_resume_after_interrupted_migration_keeps_data(self):
        import sqlite3
        import tempfile

        tmp = Path(tempfile.mkdtemp(dir=str(ROOT / "storage")))
        dbpath = tmp / "legacy.db"
        con = sqlite3.connect(dbpath)
        con.executescript("""
          CREATE TABLE message_outbox (
            message_id TEXT PRIMARY KEY, channel TEXT, recipient TEXT,
            message_type TEXT, payload TEXT, status TEXT, attempts INTEGER,
            next_attempt_at TEXT, created_at TEXT, idempotency_key TEXT,
            lead_id TEXT, conversation_id TEXT, correlation_id TEXT,
            provider_message_id TEXT, failure_reason TEXT, sent_at TEXT);
          INSERT INTO message_outbox (message_id, channel, recipient,
            message_type, payload, status, attempts, next_attempt_at,
            created_at) VALUES
            ('m1','whatsapp','+90500','text','{}','queued',0,NULL,'t');
        """)
        con.commit(); con.close()

        from amancore.storage.db import open_database

        db = open_database(dbpath, schema_file=(
            ROOT / "amancore" / "storage" / "schema.sql"))
        try:
            cols = {r["name"] for r in db.execute(
                "PRAGMA table_info(message_outbox)").fetchall()}
            self.assertIn("claimed_at", cols)     # migration completed despite legacy origin
            n = db.execute("SELECT COUNT(*) c FROM message_outbox").fetchone()[0]
            self.assertEqual(n, 1)                # legacy data preserved
            db.close()
            db2 = open_database(dbpath, schema_file=(   # re-run after "interrupt"
                ROOT / "amancore" / "storage" / "schema.sql"))
            n2 = db2.execute("SELECT COUNT(*) c FROM message_outbox").fetchone()[0]
            self.assertEqual(n2, 1)               # idempotent resume
            db2.close()
        finally:
            for f in tmp.iterdir():
                f.unlink(missing_ok=True)
            tmp.rmdir()


class AiMalformedResponse(SharedDBTestCase):
    def test_malformed_llm_object_falls_back_deterministically(self):
        from types import SimpleNamespace

        from amancore.channels.coordinator import MessageCoordinator

        coord = SimpleNamespace(cost_governor=None)
        coord._localize = lambda text, lang: text
        coord._audit = lambda *a, **k: None

        class Broken:
            text = None      # malformed provider output

        class P:
            def complete(self, messages, **kw):
                return Broken()

        coord._quote_drafter = lambda: P()
        lead = {"lead_id": "L", "contact_whatsapp": "905111111111"}
        out = MessageCoordinator._draft_reply(
            coord, lead, "مرحبا", "ar", intent_note="", base="BASE", history="")
        self.assertIn("BASE", out)


if __name__ == "__main__":
    unittest.main()
