import unittest
from pathlib import Path

from amancore.ops.backup import BackupService
from amancore.ops.recovery import RecoveryService
from tests.common import TempDirTestCase, make_db


class BackupServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.root = self.tmp / "proj"
        self.root.mkdir(exist_ok=True)
        (self.root / "storage").mkdir(parents=True, exist_ok=True)
        # create a fake production db for backup
        import sqlite3

        conn = sqlite3.connect(self.root / "storage" / "aman_core.db")
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()
        (self.root / "amancore" / "business_brain").mkdir(parents=True, exist_ok=True)
        (self.root / "amancore" / "business_brain" / "data").mkdir(parents=True, exist_ok=True)
        (self.root / "amancore" / "business_brain" / "data" / "v1.yaml").write_text("version: 1\n")
        (self.root / "configs").mkdir(exist_ok=True)
        (self.root / "configs" / "app.yaml").write_text("env: development\n")
        self.svc = BackupService(self.db, self.root)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_create_database_backup(self):
        result = self.svc.create_backup("database")
        self.assertEqual(result["status"], "created")
        artifact = result["kinds"]["database"]["artifacts"][0]
        self.assertTrue(Path(artifact["path"]).exists())
        self.assertTrue(artifact["sha256"])
        self.assertGreater(artifact["size_bytes"], 0)
        # secondary copy exists
        self.assertTrue(Path(artifact["secondary"]).exists())

    def test_create_all_kinds(self):
        result = self.svc.create_backup("all")
        for kind in ("database", "business_brain", "configs", "audit"):
            self.assertEqual(result["kinds"][kind]["status"], "created", kind)

    def test_verify_backup_checksum_and_integrity(self):
        result = self.svc.create_backup("database")
        backup_id = result["kinds"]["database"]["artifacts"][0]["backup_id"]
        verified = self.svc.verify_backup(backup_id)
        self.assertEqual(verified["status"], "verified")
        self.assertTrue(verified["checks"]["checksum"])
        self.assertEqual(verified["checks"]["integrity"], "ok")

    def test_verify_fails_on_tampered_backup(self):
        result = self.svc.create_backup("database")
        artifact = result["kinds"]["database"]["artifacts"][0]
        # tamper with the file
        with open(artifact["path"], "r+b") as f:
            f.write(b"corrupt")
        verified = self.svc.verify_backup(artifact["backup_id"])
        self.assertEqual(verified["status"], "failed")
        self.assertFalse(verified["checks"]["checksum"])

    def test_list_backups(self):
        self.svc.create_backup("database")
        rows = self.svc.list_backups()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "database")

    def test_latest_verified_database(self):
        # BAK-103: backups are now auto-verified inline — verified immediately after create
        self.svc.create_backup("database")
        latest = self.svc.latest_verified_database()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["status"], "verified")

    def test_restore_to_temp_never_touches_production(self):
        result = self.svc.create_backup("database")
        backup_id = result["kinds"]["database"]["artifacts"][0]["backup_id"]
        self.svc.verify_backup(backup_id)
        restored = self.svc.restore_to_temp(backup_id)
        self.assertTrue(restored.exists())
        # production db untouched
        import sqlite3

        conn = sqlite3.connect(self.root / "storage" / "aman_core.db")
        try:
            conn.execute("SELECT COUNT(*) FROM t").fetchone()
        finally:
            conn.close()


class RecoveryServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.root = self.tmp / "proj"
        self.root.mkdir(exist_ok=True)
        (self.root / "storage").mkdir(parents=True, exist_ok=True)
        import sqlite3

        conn = sqlite3.connect(self.root / "storage" / "aman_core.db")
        # real schema tables for the tables-present check
        from amancore.storage.db import open_database

        open_database(self.root / "storage" / "aman_core.db", Path(__file__).resolve().parent.parent.parent
                      / "amancore" / "storage" / "schema.sql").close()
        conn = sqlite3.connect(self.root / "storage" / "aman_core.db")
        conn.execute("INSERT INTO leads (lead_id, created_at, updated_at) VALUES ('l1', '2026-01-01', '2026-01-01')")
        conn.commit()
        conn.close()
        self.svc = BackupService(self.db, self.root)
        self.recovery = RecoveryService(self.db, self.root, backup_service=self.svc)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_recovery_test_pass_with_verified_backup(self):
        self.svc.create_backup("database")
        self.svc.verify_latest("database")
        result = self.recovery.run_recovery_test()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["checks"]["integrity"])
        self.assertTrue(result["checks"]["tables"])

    def test_recovery_skipped_without_backup(self):
        result = self.recovery.run_recovery_test()
        self.assertEqual(result["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
