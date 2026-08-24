"""SQLite database access. This module is the ONLY one that opens the DB.

Agents and business modules must go through the CRM Data Service or the
dedicated services; they never import `sqlite3` directly (enforced by an
architecture test).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..errors import IntegrityError


class Database:
    """SQLite wrapper. WAL + one connection PER THREAD (threading.local):
    the HTTP server, worker and console threads each get an isolated
    connection, eliminating cross-thread transaction/commit races while
    SQLite itself serializes writers at the file level."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        conn = self._thread_conn()
        conn.execute("PRAGMA journal_mode = WAL")
        # NOTE: check_same_thread=False is required by the JobRunner (worker
        # threads). Scheduler concurrency is 1 and SQLite serializes writes.

    def _thread_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn = conn
        return conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._thread_conn().execute(sql, params)

    def backup_to(self, dst_path) -> None:
        """Consistent online backup via the sqlite backup API (same thread)."""
        dst_conn = sqlite3.connect(str(dst_path))
        try:
            self._thread_conn().backup(dst_conn)
        finally:
            dst_conn.close()

    def integrity_ok(self) -> bool:
        row = self._thread_conn().execute("PRAGMA integrity_check").fetchone()
        return row is not None and row[0] == "ok"

    def executescript(self, sql: str) -> None:
        self._thread_conn().executescript(sql)

    def commit(self) -> None:
        self._thread_conn().commit()

    def rollback(self) -> None:
        self._thread_conn().rollback()

    def transaction(self):
        """Context manager committing on success, rolling back on error."""
        return _Transaction(self._thread_conn())

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def apply_schema(self, schema_sql: str) -> None:
        self._thread_conn().executescript(schema_sql)


class _Transaction:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        return False


# Idempotent additive migrations for databases created before a column was
# added. CREATE TABLE IF NOT EXISTS does not alter existing tables, so new
# columns are added here via PRAGMA check.
_COLUMN_MIGRATIONS = [
    ("leads", "website", "TEXT"),
    ("leads", "fit_signals", "TEXT"),
    ("leads", "provenance", "TEXT"),
    ("content_items", "platform", "TEXT"),
    ("content_items", "topic", "TEXT"),
    ("content_items", "angle", "TEXT"),
    ("content_items", "hook", "TEXT"),
    ("content_items", "cta", "TEXT"),
    ("content_items", "source_research_ids", "TEXT"),
    ("content_items", "approval_status", "TEXT"),
    ("content_items", "risk_level", "TEXT"),
    ("content_items", "quality_json", "TEXT"),
    ("content_items", "content_hash", "TEXT"),
    ("conversations", "language", "TEXT"),
    ("conversations", "objections", "TEXT"),
    ("conversations", "last_message_at", "TEXT"),
    ("conversations", "next_action", "TEXT"),
    ("conversations", "next_followup_at", "TEXT"),
    ("conversations", "mode", "TEXT NOT NULL DEFAULT 'AI_ACTIVE'"),
    ("opportunities", "reason", "TEXT"),
    ("channel_messages", "media_kind", "TEXT"),
    ("channel_messages", "media_ref", "TEXT"),
    ("channel_messages", "outbox_message_id", "TEXT"),
    ("channel_messages", "wa_message_id", "TEXT"),
    ("channel_messages", "lead_id", "TEXT"),
    ("channel_messages", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("channel_messages", "reaction", "TEXT"),
    ("channel_messages", "quoted_wamid", "TEXT"),
    ("message_outbox", "claimed_at", "TEXT"),      # OUT-202 atomic claims
    ("message_outbox", "claim_token", "TEXT"),
]


def ensure_unique_indexes(db: Database) -> None:
    """OUT-203 (C2): enforce wa_message_id uniqueness on existing databases.

    Removes duplicate rows first (keeps lowest rowid = original delivery),
    then creates the partial unique index. Safe to run repeatedly.
    """
    dupes = db.execute(
        "SELECT wa_message_id FROM channel_messages WHERE wa_message_id IS NOT NULL "
        "GROUP BY wa_message_id HAVING COUNT(*) > 1"
    ).fetchall()
    for r in dupes:
        cur = db.execute(
            "DELETE FROM channel_messages WHERE wa_message_id = ? AND rowid NOT IN "
            "(SELECT MIN(rowid) FROM channel_messages WHERE wa_message_id = ?)",
            (r["wa_message_id"], r["wa_message_id"]),
        )
        db.commit()
        import logging

        logging.getLogger("amancore.storage").warning(
            "out203.dedupe wamid=%s removed=%d", r["wa_message_id"], cur.rowcount
        )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_messages_wamid "
        "ON channel_messages (wa_message_id) WHERE wa_message_id IS NOT NULL"
    )
    db.commit()


def ensure_columns(db: Database) -> None:
    """Add missing columns (idempotent) for additive schema evolution."""
    for table, col, typ in _COLUMN_MIGRATIONS:
        existing = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    db.commit()


def _split_schema(sql: str) -> tuple[str, str]:
    """Split schema into (tables+pragma, indexes) so additive columns land
    before indexes that reference them."""
    tables: list[str] = []
    indexes: list[str] = []
    current = tables
    for line in sql.splitlines():
        if line.lstrip().upper().startswith("CREATE INDEX"):
            current = indexes
        current.append(line)
    return "\n".join(tables), "\n".join(indexes)


def open_database(path: Path, schema_file: Path | None = None) -> Database:
    """Open (and optionally initialize) the AmanCore database."""
    db = Database(path)
    if schema_file is not None and schema_file.exists():
        tables_sql, index_sql = _split_schema(schema_file.read_text(encoding="utf-8"))
        db.apply_schema(tables_sql)
        ensure_columns(db)
        ensure_unique_indexes(db)
        if index_sql.strip():
            db.apply_schema(index_sql)
    return db
