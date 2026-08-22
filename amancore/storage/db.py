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


def open_database(path: Path, schema_file: Path | None = None) -> Database:
    """Open (and optionally initialize) the AmanCore database."""
    db = Database(path)
    if schema_file is not None and schema_file.exists():
        db.apply_schema(schema_file.read_text(encoding="utf-8"))
    return db
