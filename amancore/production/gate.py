"""ProductionGateService — separates Technical Ready from Production Enabled.

The golden rule (spec section 31):
    Production mode ≠ configured mode.
    Production mode = official verification + security + policy + opt-out +
                      human takeover + idempotency + audit + health + owner readiness.

production_enabled defaults to false. No agent/tool/service may send a real
message while it is false — even if credentials exist.
"""

from __future__ import annotations

import os

from ..errors import ProductionNotEnabledError
from ..ids import utcnow
from ..storage.db import Database

GATES = [
    ("official_docs_verified", "api_docs_verified"),
    ("account_configuration_verified", "account_configuration_verified"),
    ("business_verification_complete", "business_verification_complete"),
    ("phone_number_configured", "phone_number_configured"),
    ("webhook_https_reachable", "webhook_reachable"),
    ("webhook_verification_successful", "webhook_verified"),
    ("signature_validation_tested", "signature_tested"),
    ("outbound_test_successful", "outbound_tested"),
    ("template_requirements_satisfied", "template_requirements_satisfied"),
    ("optout_tested", "optout_tested"),
    ("human_takeover_tested", "human_takeover_tested"),
    ("idempotency_tested", "idempotency_tested"),
    ("outbox_tested", "outbox_tested"),
    ("policy_tested", "policy_tested"),
    ("audit_tested", "audit_tested"),
    ("health_check_pass", "health_pass"),
    ("owner_alert_configured", "owner_alert_configured"),
    ("secrets_configured", "secrets_configured"),
    ("backup_verified", "backup_verified"),
    ("recovery_test_passed", "recovery_test_passed"),
    ("runbooks_exist", "runbooks_exist"),
    ("alert_transport_works", "alert_transport_works"),
    ("owner_destination_configured", "owner_destination_configured"),
]

REQUIRED_SECRET_ENVS = [
    "AMANCORE_BRIDGE_TOKEN", "BRIDGE_INGRESS_TOKEN",
]


class ProductionGateService:
    def __init__(
        self,
        config: dict,
        *,
        db: Database | None = None,
        env: dict | None = None,
    ):
        self.config = config
        self.db = db
        # explicit empty env must stay empty (test isolation) — only None
        # falls back to the real process environment.
        self.env = os.environ if env is None else dict(env)

    # ---- low-level checks ---------------------------------------------
    def _config_ok(self) -> bool:
        mode = self.config.get("environment", {}).get("mode", "mock")
        return mode in ("mock", "sandbox", "production")

    def _production_enabled(self) -> bool:
        return bool(self.config.get("environment", {}).get("production_enabled", False))

    def _secrets_present(self) -> bool:
        return all(bool(self.env.get(k)) for k in REQUIRED_SECRET_ENVS)

    def _official_verification(self, gate_key: str) -> bool:
        ov = self.config.get("official_verification", {})
        return bool(ov.get(gate_key, False))

    def _health_pass(self) -> bool:
        try:
            from ..config import load_config
            from ..health import run_health_checks

            root = self.config.get("_root")
            if not root:
                return False
            results = run_health_checks(root)
            return all(status == "PASS" for status, _ in results.values())
        except Exception:  # noqa: BLE001 — gate must never raise
            return False

    # ---- evaluation -----------------------------------------------------
    def check(self, run_health: bool = False) -> dict:
        """Evaluate every gate. Returns statuses + overall verdict."""
        statuses: list[dict] = []
        for name, key in GATES:
            if name == "secrets_configured":
                ok = self._secrets_present()
            elif name == "health_check_pass":
                ok = self._official_verification("health_pass")
                if run_health:  # optionally live-verify on top of the declared flag
                    ok = ok and self._health_pass()
            else:
                ok = self._official_verification(key)
            statuses.append({"gate": name, "status": "PASS" if ok else "FAIL"})

        # dynamic checks
        prod_enabled = self._production_enabled()
        mode = self.config.get("environment", {}).get("mode", "mock")
        webhook_url = self.config.get("environment", {}).get("webhook_url", "")
        statuses.append({"gate": "production_enabled", "status": "PASS" if prod_enabled else "FAIL"})
        statuses.append({"gate": "configuration_valid", "status": "PASS" if self._config_ok() else "FAIL"})
        statuses.append({
            "gate": "webhook_url_https",
            "status": "PASS" if (webhook_url or "").startswith("https://") else "FAIL",
        })
        # operational dynamic gates
        if self.db is not None:
            try:
                row = self.db.execute("PRAGMA integrity_check").fetchone()
                statuses.append({"gate": "database_integrity",
                                 "status": "PASS" if row[0] == "ok" else "FAIL"})
            except Exception:  # noqa: BLE001
                statuses.append({"gate": "database_integrity", "status": "FAIL"})
        statuses.append({"gate": "runbooks_present", "status": "PASS" if self._runbooks_ok() else "FAIL"})
        statuses.append({"gate": "alert_transport_works", "status": "PASS" if self._transport_ok() else "FAIL"})

        failed = [s for s in statuses if s["status"] == "FAIL" and s["gate"] != "production_enabled"]
        if not prod_enabled:
            verdict = "NOT_READY" if failed else "CONDITIONAL"
        elif failed:
            verdict = "NOT_READY"
        else:
            verdict = "READY"
        return {
            "verdict": verdict,
            "production_enabled": prod_enabled,
            "mode": mode,
            "checked_at": utcnow(),
            "gates": statuses,
            "official_verification_status": self.config.get("official_verification", {}).get(
                "status", "OFFICIAL_VERIFICATION_PENDING"
            ),
        }

    def _runbooks_ok(self) -> bool:
        root = self.config.get("_root")
        if not root:
            return False
        runbooks_dir = root / "docs" / "runbooks"
        try:
            return runbooks_dir.exists() and len(list(runbooks_dir.glob("*.md"))) >= 10
        except Exception:  # noqa: BLE001
            return False

    def _transport_ok(self) -> bool:
        """A real owner transport must be AVAILABLE (telegram/email creds exist).
        The owner's chosen destination is the separate owner_destination_configured gate."""
        import os

        telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
        email = bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_TO"))
        return telegram or email

    def assert_production_send_allowed(self, channel: str = "whatsapp") -> None:
        """Safety rule: no real send unless production_enabled AND mode=production."""
        mode = self.config.get("environment", {}).get("mode", "mock")
        if not self._production_enabled() or mode != "production":
            raise ProductionNotEnabledError(
                f"external send blocked for {channel}: production_enabled={self._production_enabled()}, mode={mode}"
            )


def block_unless_production_enabled(config: dict) -> None:
    """Guard used by providers: raise if a real send is attempted while gated."""
    ProductionGateService(config).assert_production_send_allowed()
