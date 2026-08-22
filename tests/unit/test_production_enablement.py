"""Phase 3I tests — production enablement/disablement + scheduler graceful shutdown."""

import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path

from amancore.errors import ProductionNotEnabledError
from amancore.production.enablement import (
    ENABLE_PHRASE,
    ProductionEnablementError,
    ProductionEnablementService,
)
from amancore.production.gate import ProductionGateService

ROOT = Path(__file__).resolve().parent.parent.parent

READY_OFFICIAL_VERIFICATION = {
    "status": "VERIFIED", "api_docs_verified": True,
    "account_configuration_verified": True, "business_verification_complete": True,
    "phone_number_configured": True, "webhook_reachable": True, "webhook_verified": True,
    "signature_tested": True, "outbound_tested": True, "template_requirements_satisfied": True,
    "optout_tested": True, "human_takeover_tested": True, "idempotency_tested": True,
    "outbox_tested": True, "policy_tested": True, "audit_tested": True,
    "health_pass": True, "owner_alert_configured": True, "secrets_configured": True,
    "backup_verified": True, "recovery_test_passed": True, "runbooks_exist": True,
    "alert_transport_works": True, "owner_destination_configured": True,
}

PRODUCTION_YAML = """\
# Production configuration (test fixture).
environment:
  mode: mock              # mock | sandbox | production
  api_version: v24.0
  base_url: https://graph.facebook.com
  webhook_url: ""
  production_enabled: false

official_verification:
  status: OFFICIAL_VERIFICATION_PENDING
"""


def _ready_gate_report():
    import os

    config = {
        "environment": {
            "mode": "production", "api_version": "v24.0",
            "webhook_url": "https://example.com/webhook/whatsapp",
            "production_enabled": False,
        },
        "official_verification": dict(READY_OFFICIAL_VERIFICATION),
        "_root": ROOT,
    }
    secrets = {
        "WHATSAPP_VERIFY_TOKEN": "t", "WHATSAPP_APP_SECRET": "s",
        "WHATSAPP_ACCESS_TOKEN": "a", "WHATSAPP_PHONE_NUMBER_ID": "p",
    }
    # alert transport dynamic check reads the real process environment
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "test-chat"
    try:
        return ProductionGateService(config, env=secrets).check()
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)


def _not_ready_gate_report():
    config = {
        "environment": {"mode": "mock", "api_version": "v24.0", "webhook_url": "",
                        "production_enabled": False},
        "official_verification": {"status": "OFFICIAL_VERIFICATION_PENDING"},
        "_root": ROOT,
    }
    return ProductionGateService(config, env={}).check()


class ProductionEnableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "production.yaml"
        self.config_path.write_text(PRODUCTION_YAML, encoding="utf-8")
        from amancore.ops.jobs import JobStore  # noqa: F401  (schema import side effect)
        from tests.common import make_db

        self.db = make_db(Path(self.tmp.name) / "audit.db")
        self.svc = ProductionEnablementService(self.config_path, db=self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_enable_blocked_when_not_ready(self):
        svc = self.svc
        with self.assertRaises(ProductionNotEnabledError):
            svc.enable(_not_ready_gate_report(), ENABLE_PHRASE)
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("production_enabled: false", text)
        self.assertIn("mode: mock", text)

    def test_enable_requires_exact_confirmation_phrase(self):
        svc = self.svc
        for bad in ("yes", "y", "CONFIRM", "confirm production enable", ""):
            with self.assertRaises(ProductionEnablementError):
                svc.enable(_ready_gate_report(), bad)
        self.assertIn("production_enabled: false", self.config_path.read_text(encoding="utf-8"))

    def test_enable_writes_production_state_and_preserves_comments(self):
        svc = self.svc
        result = svc.enable(_ready_gate_report(), ENABLE_PHRASE, actor="owner-test")
        self.assertTrue(result["enabled"])
        self.assertEqual(result["mode"], "production")
        self.assertTrue(result["audit_id"])
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("production_enabled: true", text)
        self.assertIn("mode: production", text)
        # comments and unrelated keys survive the surgical edit
        self.assertIn("# Production configuration (test fixture).", text)
        self.assertIn("webhook_url: \"\"", text)

    def test_disable_is_idempotent_and_audited(self):
        svc = self.svc
        # config starts disabled -> first disable is a no-op flagged as such
        noop = svc.disable(actor="owner-test", reason="noop")
        self.assertTrue(noop["already_disabled"])
        # after a real enable, disable performs an audited state change
        svc.enable(_ready_gate_report(), ENABLE_PHRASE, actor="owner-test")
        first = svc.disable(actor="owner-test", reason="incident drill")
        second = svc.disable(actor="owner-test", reason="again")
        self.assertFalse(first["enabled"])
        self.assertFalse(first["already_disabled"])
        self.assertTrue(first["audit_id"])
        self.assertFalse(second["enabled"])
        self.assertTrue(second["already_disabled"])
        self.assertIn("production_enabled: false", self.config_path.read_text(encoding="utf-8"))

    def test_full_cycle_enable_then_disable(self):
        svc = self.svc
        enabled = svc.enable(_ready_gate_report(), ENABLE_PHRASE, actor="owner-test")
        self.assertTrue(enabled["enabled"])
        disabled = svc.disable(actor="owner-test", reason="rollback drill")
        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["mode"], "mock")


class SchedulerGracefulShutdownTests(unittest.TestCase):
    def test_run_loop_stops_on_sigterm(self):
        import os

        from amancore.ops.jobs import JobRunner, JobStore
        from amancore.ops.scheduler import SchedulerRuntime
        from tests.common import make_db

        with tempfile.TemporaryDirectory() as td:
            db = make_db(Path(td) / "test.db")
            try:
                store = JobStore(db)
                runtime = SchedulerRuntime(
                    store, JobRunner(store, {}),
                    {"scheduler": {"poll_interval_seconds": 1}},
                )

                def _send_later():
                    time.sleep(0.3)
                    os.kill(os.getpid(), signal.SIGTERM)

                t = threading.Thread(target=_send_later)
                t.start()
                start = time.monotonic()
                runtime.run_loop(interval_seconds=1)
                elapsed = time.monotonic() - start
                t.join()
                self.assertLess(elapsed, 5.0)
            finally:
                db.close()

    def test_run_loop_max_iterations_returns(self):
        from amancore.ops.jobs import JobRunner, JobStore
        from amancore.ops.scheduler import SchedulerRuntime
        from tests.common import make_db

        with tempfile.TemporaryDirectory() as td:
            db = make_db(Path(td) / "test.db")
            try:
                store = JobStore(db)
                runtime = SchedulerRuntime(store, JobRunner(store, {}), {})
                start = time.monotonic()
                runtime.run_loop(interval_seconds=0, max_iterations=2)
                self.assertLess(time.monotonic() - start, 10.0)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
