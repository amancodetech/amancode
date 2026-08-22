"""AmanCore CLI — local operator commands.

Usage:  python -m amancore.cli <command>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _health(args) -> int:
    from .health import print_health_report, run_health_checks

    return print_health_report(run_health_checks(ROOT))


def _test(args) -> int:
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-t", str(ROOT)]
    )


def _brain_validate(args) -> int:
    from .business_brain.store import BrainStore
    from .business_brain.validator import validate_brain

    store = BrainStore(ROOT / "amancore" / "business_brain")
    version, data = store.current()
    errors = validate_brain(data)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print(f"Business Brain v{version}: valid")
    return 0


def _brain_versions(args) -> int:
    from .business_brain.store import BrainStore

    store = BrainStore(ROOT / "amancore" / "business_brain")
    for v in store.versions():
        print(f"v{v['version']:<4} {v['approval_status']:<10} {v['reason']} (by {v['created_by']})")
    return 0


def _audit_recent(args) -> int:
    from .config import load_config
    from .services.audit import AuditService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    audit = AuditService(db)
    for e in audit.query(limit=args.n):
        print(f"{e['timestamp']}  {e['action']:<30} {e['resource']}  {e.get('result','')}")
    db.close()
    return 0


def _config_check(args) -> int:
    from .config import load_config

    cfg = load_config(ROOT)
    print(f"env          : {cfg.app.get('env')}")
    print(f"database_path: {cfg.database_path}")
    print(f"shadow_rate  : {cfg.shadow_rate}")
    print(f"markets      : {list(cfg.pricing.get('market_multiplier', {}).keys())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aman-core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    sub.add_parser("test")
    sub.add_parser("brain").add_argument("sub", choices=["validate", "versions"])
    sub.add_parser("config").add_argument("sub", choices=["check"])
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("sub", choices=["recent"])
    p_audit.add_argument("-n", type=int, default=20)

    args = parser.parse_args(argv)
    if args.cmd == "health":
        return _health(args)
    if args.cmd == "test":
        return _test(args)
    if args.cmd == "brain":
        return _brain_validate(args) if args.sub == "validate" else _brain_versions(args)
    if args.cmd == "audit":
        return _audit_recent(args)
    if args.cmd == "config":
        return _config_check(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
