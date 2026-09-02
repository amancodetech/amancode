"""Process-Safe Isolated Test Database Fixture and Management."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Generator

from amancore.storage.db import (
    Database,
    ensure_channel_neutral,
    ensure_columns,
    ensure_unique_indexes,
    open_database,
)
from tests.fixtures.isolation import assert_not_production_database

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "amancore" / "storage" / "schema.sql"

TABLES_TO_WIPE = (
    "scope_items",
    "scope_versions",
    "project_scopes",
    "open_questions",
    "requirement_conflicts",
    "project_decisions",
    "requirements",
    "channel_messages",
    "message_outbox",
    "platform_identities",
    "jobs",
    "alerts",
    "incidents",
    "compliance_overrides",
    "cost_counters",
    "idempotency_keys",
    "events",
    "conversations",
    "opportunities",
    "support_cases",
    "leads",
    "content_items",
    "proposals",
    "pricing_snapshots",
)


def assert_test_database(db: Database) -> None:
    """Explicitly verify that the database instance points to a temporary/test file."""
    assert_not_production_database(db.path)
    row = db.execute("PRAGMA foreign_keys").fetchone()
    if row is None or row[0] != 1:
        raise RuntimeError("DATABASE CONFIG ERROR: PRAGMA foreign_keys is not ON!")


@contextlib.contextmanager
def isolated_db(prefix: str = "test_db_") -> Generator[Database, None, None]:
    """Provide a completely process-isolated temporary SQLite database with schema initialized.
    
    Guarantees:
    - Dedicated process- and worker-specific temp folder
    - Schema & indexes initialized
    - Foreign keys ON and WAL mode active
    - Clean teardown on exit
    """
    worker_id = os.environ.get("TEST_WORKER_ID") or os.environ.get("PYTEST_XDIST_WORKER") or f"pid_{os.getpid()}"
    safe_prefix = f"{prefix}{worker_id}_"

    with tempfile.TemporaryDirectory(prefix=safe_prefix) as temp_dir:
        db_path = Path(temp_dir) / f"{worker_id}_isolated.db"
        assert_not_production_database(db_path)

        db = open_database(db_path, SCHEMA_PATH)
        ensure_columns(db)
        ensure_channel_neutral(db)
        ensure_unique_indexes(db)
        assert_test_database(db)

        try:
            yield db
        finally:
            db.close()


@contextlib.contextmanager
def transactional_db(db: Database) -> Generator[Database, None, None]:
    """Single-connection rollback fixture for fast lightweight tests."""
    assert_test_database(db)
    db.execute("BEGIN")
    try:
        yield db
    finally:
        db.execute("ROLLBACK")


def wipe_db(db: Database) -> None:
    """Delete all rows from mutable tables in FK-safe order."""
    assert_test_database(db)
    prev = db.execute("PRAGMA foreign_keys").fetchone()[0]
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        for t in TABLES_TO_WIPE:
            try:
                db.execute(f"DELETE FROM {t}")
            except Exception:
                pass
    finally:
        if prev:
            db.execute("PRAGMA foreign_keys = ON")
