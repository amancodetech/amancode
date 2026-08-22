"""SQLite database access. This module is the ONLY one that opens the DB.

Agents and business modules must go through the CRM Data Service or the
dedicated services; they never import `sqlite3` directly (enforced by an
architecture test).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..errors import IntegrityError


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executescript(self, sql: str) -> None:
        self._conn.executescript(sql)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def transaction(self):
        """Context manager committing on success, rolling back on error."""
        return _Transaction(self._conn)

    def close(self) -> None:
        self._conn.close()

    def apply_schema(self, schema_sql: str) -> None:
        self._conn.executescript(schema_sql)
        self._conn.commit()


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
]


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
        if index_sql.strip():
            db.apply_schema(index_sql)
    return db
