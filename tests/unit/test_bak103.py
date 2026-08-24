"""BAK-103: honest backups — raise on failure, verify inline, restore test."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.ops.backup import BackupService  # noqa: E402
from amancore.storage.db import Database, open_database  # noqa: E402


class BackupHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "storage").mkdir()
        (root / "amancore" / "storage").mkdir(parents=True)
        schema = ROOT / "amancore" / "storage" / "schema.sql"
        self.db_path = root / "storage" / "aman_core.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(schema.read_text())
        conn.execute("INSERT INTO leads (lead_id, status, created_at, updated_at) "
                     "VALUES ('L1','new','2026-08-24','2026-08-24')")
        conn.commit(); conn.close()
        self.root = root
        self.db = open_database(self.db_path, schema)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _svc(self) -> BackupService:
        return BackupService(self.db, self.root, database_path=self.db_path)

    def test_successful_backup_inline_verified(self):
        result = self._svc().create_backup("database")
        art = result["kinds"]["database"]["artifacts"][0]
        self.assertEqual(art["integrity"], "ok")
        self.assertGreater(art["size_bytes"], 4096)
        self.assertTrue(Path(art["secondary"]).exists())  # secondary copied
        v = self._svc().verify_latest("database")
        self.assertEqual(v["status"], "verified")
        self.assertEqual(v["checks"]["integrity"], "ok")

    def test_missing_source_raises(self):
        svc = BackupService(self.db, self.root,
                            database_path=Path(self.tmp.name) / "nope.db")
        with self.assertRaises(FileNotFoundError):
            svc.create_backup("database")  # RAISES — not {"status":"failed"}

    def test_hollow_snapshot_rejected(self):
        """A <4KB copy must be rejected — the silent-empty-backup bug class."""
        calls = {"n": 0}
        real = Database.backup_to

        def fake(self, dst):  # write a hollow file instead of a real backup
            Path(dst).write_bytes(b"SQLite format 3\0" + b"\0" * 100)
            calls["n"] += 1

        Database.backup_to = fake
        try:
            with self.assertRaises(RuntimeError):
                self._svc().create_backup("database")
        finally:
            Database.backup_to = real
        self.assertEqual(calls["n"], 1)

    def test_restore_test_end_to_end(self):
        from types import SimpleNamespace

        from amancore.ops.registry import JobRegistry

        svc = self._svc()
        svc.create_backup("database")
        latest = svc.latest_verified_database()
        self.assertIsNotNone(latest)
        # NOTE: deliberately NO load_config(ROOT, mutate_environ=False) here — it would inject the
        # real .env into os.environ (config.load_env uses setdefault) and
        # pollute every later test (discovered during BAK-103; see report).
        cfg = SimpleNamespace(database_path=str(self.db_path))
        handlers = JobRegistry(self.db, cfg, self.root).handlers()
        result = handlers["backup.restore_test"]({})
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["row_counts"]["leads"], 1)


if __name__ == "__main__":
    unittest.main()
