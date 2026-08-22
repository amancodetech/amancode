#!/usr/bin/env python3
"""Backup the AmanCore SQLite database using the sqlite backup API."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "storage" / "aman_core.db"
OUT = ROOT / "backups"


def main() -> int:
    if not SRC.exists():
        print(f"no database at {SRC}; nothing to back up")
        return 1
    OUT.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = OUT / f"aman_core-{ts}.db"
    src_conn = sqlite3.connect(SRC)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    print(f"backup -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
