"""Shared single-database test fixture (user directive: ONE db for all tests).

Every suite previously created/deleted its OWN sqlite file per class — slow
churn and drift. Now: one on-disk WAL database at storage/_amancore_tests.db,
schema applied ONCE per process, tables wiped between tests.

Concurrency suites (outbox atomic claims, lease races) still open their OWN
Database instances — against this SAME shared file, because multi-connection
WAL behavior IS the thing under test.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from amancore.storage.db import (  # noqa: E402
    Database, ensure_channel_neutral, ensure_columns, ensure_unique_indexes,
)

TEST_DB_PATH = ROOT / "storage" / "_amancore_tests.db"
SCHEMA_PATH = ROOT / "amancore" / "storage" / "schema.sql"

_SCHEMA_READY = False

#: wipe order respects FK dependencies; audit/business_brain are permanent
TABLES_TO_WIPE = (
    "channel_messages", "message_outbox", "platform_identities", "jobs",
    "alerts", "incidents", "compliance_overrides", "cost_counters",
    "idempotency_keys", "events", "conversations", "opportunities",
    "support_cases", "leads", "content_items", "proposals", "pricing_snapshots",
)


def fresh_db() -> Database:
    """Open the shared test DB; apply schema/migrations exactly once."""
    global _SCHEMA_READY
    db = Database(TEST_DB_PATH)
    if not _SCHEMA_READY:
        db.apply_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
        ensure_columns(db)
        ensure_channel_neutral(db)
        ensure_unique_indexes(db)
        _SCHEMA_READY = True
    return db


def wipe(db: Database) -> None:
    """Delete rows from mutable tables (fast, keeps schema warm)."""
    prev = db.execute("PRAGMA foreign_keys").fetchone()[0]
    db.execute("PRAGMA foreign_keys = OFF")
    for t in TABLES_TO_WIPE:
        try:
            db.execute(f"DELETE FROM {t}")
        except Exception:  # noqa: BLE001 — table may not exist in older schema
            pass
    db.execute(f"PRAGMA foreign_keys = {int(prev)}")
    db.commit()


class SharedDBTestCase(unittest.TestCase):
    """Base for suites happy with the shared DB: wiped before each test."""

    def setUp(self):
        self.db = fresh_db()
        wipe(self.db)

    def tearDown(self):
        self.db.close()
