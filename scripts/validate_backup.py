#!/usr/bin/env python3
"""Validate a SQLite backup (integrity check)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUPS = ROOT / "backups"


def main() -> int:
    files = sorted(BACKUPS.glob("*.db")) if BACKUPS.exists() else []
    if not files:
        print("no backups found")
        return 1
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else files[-1]
    conn = sqlite3.connect(target)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = row[0]
        print(f"{target.name}: integrity_check = {result}")
        return 0 if result == "ok" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
