import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PKG = ROOT / "amancore"


class BoundaryTest(unittest.TestCase):
    def _py_files(self):
        return [p for p in PKG.rglob("*.py") if "__pycache__" not in str(p)]

    def test_sqlite3_only_in_storage(self):
        offenders = []
        for f in self._py_files():
            text = f.read_text(encoding="utf-8")
            if "import sqlite3" in text or "from sqlite3" in text:
                if f.relative_to(ROOT) != Path("amancore/storage/db.py"):
                    offenders.append(str(f.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_business_brain_write_only_writer(self):
        allowed = {
            Path("amancore/business_brain/store.py"),
            Path("amancore/business_brain/writer.py"),
        }
        offenders = []
        for f in self._py_files():
            text = f.read_text(encoding="utf-8")
            if "_append_version" in text and f.relative_to(ROOT) not in allowed:
                offenders.append(str(f.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_brain_store_has_no_public_write(self):
        from amancore.business_brain.store import BrainStore

        self.assertFalse(hasattr(BrainStore, "write"))


if __name__ == "__main__":
    unittest.main()
