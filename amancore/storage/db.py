"""SQLite database access. This module is the ONLY one that opens the DB.

Agents and business modules must go through the CRM Data Service or the
dedicated services; they never import `sqlite3` directly (enforced by an
architecture test).
"""

from __future__ import annotations

import os
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
        resolved = Path(path).resolve()
        # LAST-LINE DEFENSE (LOAD-601 incident): load/mock contexts may NEVER
        # touch the production database, whatever the configuration says.
        if os.environ.get("LOAD_MOCK_LLM") or os.environ.get("AMANCORE_ISOLATED"):
            if resolved.name == "aman_core.db":
                raise RuntimeError(
                    "SAFETY GUARD: refusing to open production aman_core.db "
                    "in a load/isolated context (2026-08-24 WABA-ban incident)")
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
            # INCIDENT 2026-08-24 21:54: a thread that died mid-request left an
            # IMPLICIT write txn open forever — every other writer starved
            # ("database is locked" storm, WAL frozen 50min). Autocommit mode
            # makes each statement its own txn: lingering write locks become
            # structurally impossible. Nothing relied on multi-statement
            # implicit atomicity (zero transaction() callers audited).
            conn = sqlite3.connect(str(self.path), check_same_thread=False,
                                   isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            # LOAD-601 finding: autocommit mode pays an fsync per statement;
            # NORMAL keeps WAL durability for app-crashes while restoring
            # write throughput (power-loss window tradeoff documented).
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
        return conn

    #: LOAD-601 outcome: thread-per-request × concurrent webhooks saturated
    #: SQLite's single-writer lock; hard BUSY errors became 500 storms.
    #: Escalation policy §20 step ① — absorb contention at the wrapper with
    #: bounded retries (Postgres remains explicitly OUT of scope without an
    #: architecture decision).
    BUSY_RETRIES = 6
    BUSY_BASE_SLEEP = 0.05

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        import random
        import time as _t

        last_exc: Exception | None = None
        for attempt in range(self.BUSY_RETRIES):
            try:
                return self._thread_conn().execute(sql, params)
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc):
                    raise
                last_exc = exc
                _t.sleep(self.BUSY_BASE_SLEEP * (2 ** attempt) * (0.5 + random.random()))
        raise last_exc  # type: ignore[misc]

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
        self.conn.execute("BEGIN IMMEDIATE")   # explicit under autocommit
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
    ("conversations", "external_thread_id", "TEXT"),
    ("opportunities", "reason", "TEXT"),
    ("channel_messages", "media_kind", "TEXT"),
    ("channel_messages", "media_ref", "TEXT"),
    ("channel_messages", "outbox_message_id", "TEXT"),
    ("channel_messages", "lead_id", "TEXT"),
    ("channel_messages", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("channel_messages", "reaction", "TEXT"),
    ("message_outbox", "claimed_at", "TEXT"),      # OUT-202 atomic claims
    ("message_outbox", "claim_token", "TEXT"),
    ("leads", "consent_at", "TEXT"),               # compliance kit: opt-in
    ("leads", "consent_source", "TEXT"),
    ("message_outbox", "initiation", "TEXT"),      # 'yes' = business-initiated
    ("message_outbox", "delivery_status", "TEXT"), # provider receipts live HERE,
]                                                  # never in status (C3 closure)


def ensure_channel_neutral(db: Database) -> None:
    """One-time channel decoupling migration (idempotent, crash-safe).

    Renames the last WhatsApp-shaped columns of channel_messages to the
    canonical vocabulary, backfills platform_identities from the legacy
    leads.contact_whatsapp column, and CONVERGES partially-migrated tables
    (a prior interrupted rename can leave source+target both present —
    values are merged COALESCE-style, then the legacy column is dropped).

    SQLite RENAME keeps data intact; fresh databases created from the new
    schema.sql skip via PRAGMA checks (fresh == upgraded convergence).
    """
    cols = {r["name"] for r in db.execute("PRAGMA table_info(channel_messages)").fetchall()}
    if not cols:
        return
    pairs = [
        ("wa_id", "external_user_id"),
        ("wa_message_id", "external_message_id"),
        ("quoted_wamid", "quoted_external_message_id"),
    ]
    # legacy indexes first — they block column drops/renames otherwise
    db.execute("DROP INDEX IF EXISTS uq_channel_messages_wamid")
    db.execute("DROP INDEX IF EXISTS idx_channel_messages_wa")
    for old, new in pairs:
        if old not in cols:
            continue
        if new in cols:
            # partial-migration convergence: copy, then drop the legacy column
            db.execute(
                f"UPDATE channel_messages SET {new} = {new} "
                f"WHERE {new} IS NULL AND {old} IS NOT NULL")
            try:
                db.execute(f"ALTER TABLE channel_messages DROP COLUMN {old}")
            except Exception:  # noqa: BLE001 — very old SQLite without DROP COLUMN
                log.warning("channel_neutral: could not drop %s (old sqlite)", old)
        else:
            db.execute(f"ALTER TABLE channel_messages RENAME COLUMN {old} TO {new}")
        cols.discard(old)
        cols.add(new)
    # canonical hot-path + identity indexes (idempotent)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_channel_messages_ext "
        "ON channel_messages(external_user_id)")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_messages_external "
        "ON channel_messages(channel, external_message_id) "
        "WHERE external_message_id IS NOT NULL")
    # identity backfill: every legacy WhatsApp contact becomes an identity row
    idt = {r["name"] for r in db.execute("PRAGMA table_info(platform_identities)").fetchall()}
    if idt:
        db.execute(
            "INSERT INTO platform_identities "
            " (identity_id, lead_id, channel, external_user_id, is_primary, verified,"
            "  created_at, updated_at)"
            " SELECT lower(hex(randomblob(16))), l.lead_id, 'whatsapp',"
            "        TRIM(l.contact_whatsapp), 1, 0, l.created_at, l.updated_at"
            " FROM leads l"
            " WHERE l.contact_whatsapp IS NOT NULL AND TRIM(l.contact_whatsapp) != ''"
            " ON CONFLICT(channel, external_user_id) DO NOTHING")
    db.commit()


def ensure_unique_indexes(db: Database) -> None:
    """OUT-203 (C2): enforce external_message_id uniqueness on existing databases.

    Removes duplicate rows first (keeps lowest rowid = original delivery),
    then creates the partial unique index. Safe to run repeatedly.
    """
    dupes = db.execute(
        "SELECT external_message_id FROM channel_messages WHERE external_message_id IS NOT NULL "
        "GROUP BY external_message_id HAVING COUNT(*) > 1"
    ).fetchall()
    for r in dupes:
        cur = db.execute(
            "DELETE FROM channel_messages WHERE external_message_id = ? AND rowid NOT IN "
            "(SELECT MIN(rowid) FROM channel_messages WHERE external_message_id = ?)",
            (r["external_message_id"], r["external_message_id"]),
        )
        db.commit()
        import logging

        logging.getLogger("amancore.storage").warning(
            "out203.dedupe external_message_id=%s removed=%d",
            r["external_message_id"], cur.rowcount
        )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_messages_external "
        "ON channel_messages (channel, external_message_id) "
        "WHERE external_message_id IS NOT NULL"
    )
    # REAUD CRITICAL fix: the outbound hard gate — duplicate business sends
    # collapse to one row at the database level, not just in app logic.
    dupes = db.execute(
        "SELECT idempotency_key FROM message_outbox WHERE idempotency_key IS NOT NULL "
        "GROUP BY idempotency_key HAVING COUNT(*) > 1"
    ).fetchall()
    for r in dupes:
        db.execute(
            "DELETE FROM message_outbox WHERE idempotency_key = ? AND rowid NOT IN "
            "(SELECT MIN(rowid) FROM message_outbox WHERE idempotency_key = ?)",
            (r["idempotency_key"], r["idempotency_key"]))
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_outbox_idem "
        "ON message_outbox (idempotency_key) WHERE idempotency_key IS NOT NULL"
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
        ensure_channel_neutral(db)
        ensure_unique_indexes(db)
        if index_sql.strip():
            db.apply_schema(index_sql)
    return db
