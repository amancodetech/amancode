"""BackupService — primary + secondary local backups with checksum + verify.

Kinds: database (sqlite backup API + integrity), business_brain (versioned
yaml), configs, audit (JSON export). Every artifact: sha256 + size + registry
row. Verification proves: exists, checksum matches, integrity ok, size
reasonable, readable. SQLite access goes through the storage layer only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.backup")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BackupService:
    def __init__(self, db: Database, root: Path, database_path: Path | None = None):
        self.db = db
        self.root = Path(root)
        # BAK-103: source of truth is the configured runtime path — never a
        # hard-coded guess that can silently diverge (audit R4).
        self.database_path = Path(database_path) if database_path else (
            self.root / "storage" / "aman_core.db")
        self.backup_dir = self.root / "backup"
        self.secondary_dir = self.backup_dir / "secondary"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.secondary_dir.mkdir(parents=True, exist_ok=True)

    # ---- create ---------------------------------------------------------
    def create_backup(self, kind: str = "all") -> dict:
        """Any kind failure RAISES — JobRunner must see failure as failure
        (BAK-103/C8). A backup job that reports success on partial failure is
        the silent-data-loss bug this fixes."""
        kinds = ("database", "business_brain", "configs", "audit")
        targets = kinds if kind == "all" else (kind,)
        results = {}
        for k in targets:
            results[k] = self._backup_kind(k)  # raises on failure
        return {"status": "created", "kinds": results, "created_at": utcnow()}

    def _backup_kind(self, kind: str) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest_dir = self.backup_dir / f"{kind}-{ts}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        if kind == "database":
            artifacts = [self._backup_database(dest_dir / "aman_core.db")]
        elif kind == "business_brain":
            artifacts = self._copy_tree(self.root / "amancore" / "business_brain", dest_dir)
        elif kind == "configs":
            artifacts = self._copy_tree(self.root / "configs", dest_dir)
        elif kind == "audit":
            artifacts = [self._backup_audit(dest_dir / "audit.json")]
        else:
            raise ValueError(f"unknown backup kind: {kind}")
        # secondary copy + registry — INSIDE the raise-domain now
        for art in artifacts:
            backup_id = self._register(kind, art)
            secondary = self.secondary_dir / Path(art["path"]).name
            shutil.copy2(Path(art["path"]), secondary)
            art["secondary"] = str(secondary)
            if kind == "database":
                # inline verification persisted — a backup isn't done until verified
                verdict = self.verify_backup(backup_id)
                if verdict["status"] != "verified":
                    raise RuntimeError(f"backup verification failed: {verdict['checks']}")
        return {"kind": kind, "status": "created", "artifacts": artifacts}

    def _backup_database(self, dst: Path) -> dict:
        src = self.database_path
        if not src.exists():
            raise FileNotFoundError(f"database not found: {src}")
        src_db = Database(src)
        try:
            src_db.backup_to(dst)
        finally:
            src_db.close()
        size = dst.stat().st_size
        if size < 4096:  # empty/stale snapshot guard — never trust a hollow copy
            raise RuntimeError(f"backed-up database suspiciously small ({size} bytes): {dst}")
        chk = Database(dst)
        try:
            if not chk.integrity_ok():
                raise RuntimeError(f"backed-up database failed integrity check: {dst}")
        finally:
            chk.close()
        return {"path": str(dst), "sha256": sha256_of(dst), "size_bytes": size,
                "kind": "database", "integrity": "ok"}

    def _backup_audit(self, dst: Path) -> dict:
        rows = self.db.execute(
            "SELECT * FROM audit_events ORDER BY timestamp"
        ).fetchall()
        dst.write_text(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")
        return {"path": str(dst), "sha256": sha256_of(dst), "size_bytes": dst.stat().st_size,
                "kind": "audit"}

    def _copy_tree(self, src: Path, dest_dir: Path) -> list[dict]:
        if not src.exists():
            raise FileNotFoundError(f"source not found: {src}")
        artifacts = []
        for f in sorted(src.rglob("*")):
            if not f.is_file() or f.suffix == ".db":
                continue
            rel = f.relative_to(src)
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            artifacts.append({"path": str(target), "sha256": sha256_of(target),
                              "size_bytes": target.stat().st_size, "kind": "tree"})
        return artifacts

    def _register(self, kind: str, artifact: dict) -> str:
        backup_id = new_id()
        self.db.execute(
            "INSERT INTO backups (backup_id, kind, path, sha256, size_bytes, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'created', ?)",
            (backup_id, kind, artifact["path"], artifact["sha256"],
             artifact["size_bytes"], utcnow()),
        )
        self.db.commit()
        artifact["backup_id"] = backup_id
        return backup_id

    # ---- verify ---------------------------------------------------------
    def verify_backup(self, backup_id: str) -> dict:
        row = self.db.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
        if row is None:
            raise ValueError(f"backup not found: {backup_id}")
        b = dict(row)
        path = Path(b["path"])
        checks = {}
        checks["exists"] = path.exists()
        checks["size_reasonable"] = (b["size_bytes"] or 0) > 0 and path.stat().st_size > 0
        checks["checksum"] = sha256_of(path) == b["sha256"] if path.exists() else False
        checks["readable"] = True
        checks["integrity"] = "n/a"
        if b["kind"] == "database" and path.exists():
            try:
                db = Database(path)
                try:
                    checks["integrity"] = "ok" if db.integrity_ok() else "error"
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                checks["readable"] = False
                checks["integrity"] = str(exc)
        ok = all(v is True or v == "ok" for v in checks.values())
        self.db.execute(
            "UPDATE backups SET status = ?, verified_at = ? WHERE backup_id = ?",
            ("verified" if ok else "failed", utcnow(), backup_id),
        )
        self.db.commit()
        return {"backup_id": backup_id, "kind": b["kind"], "path": str(path),
                "status": "verified" if ok else "failed", "checks": checks}

    def verify_latest(self, kind: str = "database") -> dict | None:
        row = self.db.execute(
            "SELECT backup_id FROM backups WHERE kind = ? ORDER BY created_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        return self.verify_backup(row["backup_id"])

    def list_backups(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM backups WHERE 1=1"
        params: list = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def latest_verified_database(self) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM backups WHERE kind = 'database' AND status = 'verified' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ---- restore (to temp only — never production) ------------------------
    def restore_to_temp(self, backup_id: str) -> Path:
        """Restore a database backup to a TEMPORARY path + integrity check.
        The production DB is never touched by this method."""
        row = self.db.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
        if row is None:
            raise ValueError(f"backup not found: {backup_id}")
        b = dict(row)
        if b["kind"] != "database":
            raise ValueError(f"restore supports database backups only (got {b['kind']})")
        src = Path(b["path"])
        if not src.exists():
            raise FileNotFoundError(f"backup file missing: {src}")
        tmp = self.backup_dir / "restore-tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        dst = tmp / "restored.db"
        shutil.copy2(src, dst)
        db = Database(dst)
        try:
            ok = db.integrity_ok()
        finally:
            db.close()
        if not ok:
            raise RuntimeError("restored database failed integrity check")
        return dst
