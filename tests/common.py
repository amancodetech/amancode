"""Shared test helpers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from amancore.business_brain.store import BrainStore
from amancore.storage.db import Database, open_database

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "amancore" / "storage" / "schema.sql"
SEED = ROOT / "amancore" / "business_brain" / "data" / "v1.yaml"


def make_db(path: Path) -> Database:
    return open_database(path, SCHEMA)


def make_brain(tmp: Path) -> BrainStore:
    """Create an isolated BrainStore seeded with the real v1."""
    bdir = tmp / "brain"
    (bdir / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(SEED, bdir / "data" / "v1.yaml")
    return BrainStore(bdir)


class TempDirTestCase:
    """Mixin providing a temporary directory per test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
