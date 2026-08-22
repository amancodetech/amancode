"""Production enablement/disablement — owner-only, explicit, audited.

Golden rules enforced here:
  - No automatic enablement. The gate verdict must be READY.
  - Enable requires the exact confirmation phrase CONFIRM PRODUCTION ENABLE
    ("yes"/"y" is never accepted).
  - Disable is always allowed, fast, and audited (incident shutdown path).
  - Every transition writes an append-only audit event with actor + timestamp.

The production.yaml file is edited surgically (targeted line replacement) so
comments and unrelated keys are preserved.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..errors import ProductionNotEnabledError
from ..ids import utcnow
from ..services.audit import AuditService

ENABLE_PHRASE = "CONFIRM PRODUCTION ENABLE"


class ProductionEnablementError(Exception):
    """Raised when enable/disable preconditions are not met."""


def _read_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProductionEnablementError(f"invalid production config: {path}")
    return data


def _set_env_field(path: Path, field: str, value: str) -> None:
    """Replace `field: <old>` inside the top-level environment block only."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?m)^(  " + re.escape(field) + r":\s*).*$"
    )
    new_text, n = pattern.subn(r"\g<1>" + value, text)
    if n == 0:
        raise ProductionEnablementError(f"environment.{field} not found in {path}")
    path.write_text(new_text, encoding="utf-8")


class ProductionEnablementService:
    def __init__(self, config_path: Path, *, db=None):
        self.config_path = config_path
        self.db = db

    # ---- state ----------------------------------------------------------
    def _config(self) -> dict:
        return _read_config(self.config_path)

    def _audit(self, action: str, old: str, new: str, actor: str, reason: str | None) -> str:
        if self.db is None:
            return ""
        return AuditService(self.db).record(
            action=action,
            resource="production.environment",
            actor=actor,
            old_value=old,
            new_value=new,
            reason=reason,
            result="success",
        )

    # ---- enable -----------------------------------------------------------
    @staticmethod
    def _readiness_report(gate_report: dict) -> tuple[str, list[str]]:
        """Readiness = every gate passes except the production_enabled flag
        itself (that flag is exactly what enablement changes)."""
        failed = [
            g["gate"] for g in gate_report.get("gates", [])
            if g["status"] == "FAIL" and g["gate"] != "production_enabled"
        ]
        return gate_report.get("verdict"), failed

    def enable(
        self,
        gate_report: dict,
        confirmation: str,
        *,
        actor: str = "owner",
        dry_run: bool = False,
    ) -> dict:
        cfg = self._config()
        env = cfg.get("environment", {})
        old_state = (
            f"production_enabled={env.get('production_enabled')}, mode={env.get('mode')}"
        )
        if confirmation.strip() != ENABLE_PHRASE:
            self._audit("production.enable.rejected", old_state, old_state, actor,
                        "confirmation phrase missing or incorrect")
            raise ProductionEnablementError(
                f"refused: confirmation phrase must be exactly '{ENABLE_PHRASE}' "
                "(yes/y are not accepted)"
            )
        verdict, failed_gates = self._readiness_report(gate_report)
        if failed_gates:
            self._audit("production.enable.blocked", old_state, old_state, actor,
                        f"gate verdict={verdict}")
            raise ProductionNotEnabledError(
                f"production enable blocked: gate verdict is {verdict}; "
                f"failing gates: {failed_gates[:5]}"
            )
        if dry_run:
            return {"enabled": False, "dry_run": True, "verdict": gate_report["verdict"],
                    "checked_at": utcnow()}
        _set_env_field(self.config_path, "production_enabled", "true")
        _set_env_field(self.config_path, "mode", "production")
        audit_id = self._audit("production.enable", old_state,
                               "production_enabled=True, mode=production", actor, None)
        return {
            "enabled": True,
            "mode": "production",
            "actor": actor,
            "timestamp": utcnow(),
            "audit_id": audit_id,
        }

    # ---- disable ----------------------------------------------------------
    def disable(self, *, actor: str = "owner", reason: str | None = None) -> dict:
        cfg = self._config()
        env = cfg.get("environment", {})
        already_off = not bool(env.get("production_enabled", False))
        old_state = (
            f"production_enabled={env.get('production_enabled')}, mode={env.get('mode')}"
        )
        if not already_off:
            _set_env_field(self.config_path, "production_enabled", "false")
            _set_env_field(self.config_path, "mode", "mock")
        audit_id = self._audit("production.disable", old_state,
                               "production_enabled=False, mode=mock",
                               actor, reason or "manual disable")
        return {
            "enabled": False,
            "already_disabled": already_off,
            "mode": "mock" if not already_off else env.get("mode"),
            "actor": actor,
            "timestamp": utcnow(),
            "reason": reason,
            "audit_id": audit_id,
        }
