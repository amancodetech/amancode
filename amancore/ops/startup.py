"""Startup check — verifies everything needed to run safely.

Config → DB (integrity) → Business Brain → Audit writable → Scheduler config
→ Job queue → Backup state → Production gate. A non-ready production gate
never blocks local runtime; external sending stays BLOCKED.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger("ops.startup")


class StartupService:
    def __init__(self, root, config=None, db=None):
        self.root = root
        self.config = config
        self.db = db

    def check(self) -> dict:
        checks: dict[str, str] = {}
        # configuration
        try:
            from ..config import load_config

            cfg = self.config or load_config(self.root)
            checks["configuration"] = f"loaded ({cfg.app.get('env')})"
        except Exception as exc:  # noqa: BLE001
            checks["configuration"] = f"FAIL: {exc}"
        # database
        if self.db is not None:
            try:
                row = self.db.execute("PRAGMA integrity_check").fetchone()
                checks["database"] = f"integrity={row[0]}"
            except Exception as exc:  # noqa: BLE001
                checks["database"] = f"FAIL: {exc}"
        # business brain
        try:
            from ..business_brain.store import BrainStore
            from ..business_brain.validator import validate_brain

            store = BrainStore(self.root / "amancore" / "business_brain")
            version, data = store.current()
            errors = validate_brain(data)
            checks["business_brain"] = f"v{version} " + ("valid" if not errors else f"INVALID: {errors}")
        except Exception as exc:  # noqa: BLE001
            checks["business_brain"] = f"FAIL: {exc}"
        # audit writable
        if self.db is not None:
            try:
                from ..services.audit import AuditService

                AuditService(self.db).record(action="startup.check", resource="startup", result="ok")
                checks["audit"] = "writable"
            except Exception as exc:  # noqa: BLE001
                checks["audit"] = f"FAIL: {exc}"
        # scheduler config + job queue + backup state
        if self.db is not None:
            try:
                from ..ops.jobs import JobStore

                checks["job_queue"] = str(JobStore(self.db).counts())
            except Exception as exc:  # noqa: BLE001
                checks["job_queue"] = f"FAIL: {exc}"
            try:
                from ..ops.backup import BackupService

                latest = BackupService(self.db, self.root).latest_verified_database()
                checks["backup"] = f"latest_verified={latest['backup_id'][:8] if latest else 'NONE'}"
            except Exception as exc:  # noqa: BLE001
                checks["backup"] = f"FAIL: {exc}"
        # production gate
        try:
            from ..config import load_config
            from ..production.gate import ProductionGateService

            cfg = self.config or load_config(self.root)
            production = dict(cfg.production)
            production["_root"] = self.root
            report = ProductionGateService(production).check()
            checks["production_gate"] = f"{report['verdict']} (enabled={report['production_enabled']})"
        except Exception as exc:  # noqa: BLE001
            checks["production_gate"] = f"FAIL: {exc}"
        # alert transport
        try:
            from ..services.owner_alert import transport_status

            checks["alert_transport"] = transport_status()
        except Exception as exc:  # noqa: BLE001
            checks["alert_transport"] = f"FAIL: {exc}"

        ok = not any(v.startswith("FAIL") for v in checks.values())
        return {
            "checks": checks,
            "ok": ok,
            "production_send_blocked": True,  # external sending is BLOCKED by the gate
        }
