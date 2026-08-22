import unittest
from pathlib import Path

from amancore.services.audit import AuditService
from amancore.services.events import IdempotencyStore
from tests.common import TempDirTestCase, make_db

ROOT = Path(__file__).resolve().parent.parent.parent


class SecurityTest(TempDirTestCase, unittest.TestCase):
    def test_gitignore_excludes_env_and_db(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gi)
        self.assertIn("*.db", gi)

    def test_env_example_exists(self):
        self.assertTrue((ROOT / ".env.example").exists())

    def test_configs_contain_no_real_keys(self):
        for f in (ROOT / "configs").glob("*.yaml"):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("sk-", text)
            self.assertNotIn("AIza", text)

    def test_audit_is_append_only(self):
        self.assertFalse(hasattr(AuditService, "delete"))
        self.assertFalse(hasattr(AuditService, "update"))

    def test_idempotency_prevents_duplicate(self):
        db = make_db(self.tmp / "t.db")
        store = IdempotencyStore(db)
        self.assertTrue(store.store("k", "op", "r1"))
        self.assertFalse(store.store("k", "op", "r2"))
        db.close()


if __name__ == "__main__":
    unittest.main()
