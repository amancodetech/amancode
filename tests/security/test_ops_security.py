import os
import unittest
from pathlib import Path

from amancore.errors import ProductionNotEnabledError
from amancore.ops.alerts import AlertDispatcher, LogAlertTransport
from amancore.ops.backup import BackupService
from amancore.ops.incidents import IncidentService
from amancore.production.gate import ProductionGateService
from tests.common import TempDirTestCase, make_db

ROOT = Path(__file__).resolve().parent.parent.parent


class OpsSecurityTest(TempDirTestCase, unittest.TestCase):
    """Boundaries that must never be crossed (spec sections 45, 48, 51, 52)."""

    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_production_send_blocked(self):
        from amancore.channels.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter({
            "mode": "production", "production_enabled": False,
            "phone_number_id": "111", "base_url": "https://graph.facebook.com",
        })
        adapter.provider.access_token = "EA-fake"
        with self.assertRaises(ProductionNotEnabledError):
            adapter.send("5511", "text", "hello")

    def test_no_unsafe_restore(self):
        svc = BackupService(self.db, self.tmp)
        # no backup -> restore raises, and never touches any production path
        with self.assertRaises(ValueError):
            svc.restore_to_temp("nonexistent")

    def test_backup_contains_no_secrets(self):
        """Backup artifacts must never contain secret values."""
        # create a fake project tree with an .env-like secret
        proj = self.tmp / "proj"
        (proj / "storage").mkdir(parents=True)
        import sqlite3

        conn = sqlite3.connect(proj / "storage" / "aman_core.db")
        conn.execute("CREATE TABLE t (x)")
        conn.commit()
        conn.close()
        (proj / "configs").mkdir(parents=True)
        (proj / "configs" / "app.yaml").write_text("env: development\n")
        os.environ["WHATSAPP_ACCESS_TOKEN"] = "BACKUP_SECRET_TOKEN_XYZ"
        try:
            svc = BackupService(self.db, proj)
            result = svc.create_backup("all")
            for kind, data in result["kinds"].items():
                for art in data.get("artifacts", []):
                    content = Path(art["path"]).read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn("BACKUP_SECRET_TOKEN_XYZ", content, kind)
        finally:
            os.environ.pop("WHATSAPP_ACCESS_TOKEN", None)

    def test_alert_delivered_message_has_no_secrets(self):
        """The DELIVERED message (title/summary/action) must never carry secrets.
        Internal evidence is stored separately by design (incident evidence)."""
        class SpyTransport(LogAlertTransport):
            sent_messages = []

            def send(self, alert):
                SpyTransport.sent_messages.append(
                    f"{alert['title']} {alert.get('summary', '')} {alert.get('action_required', '')}"
                )
                return {"transport": "log", "delivered": True}

        dispatcher = AlertDispatcher(self.db, transport=SpyTransport())
        dispatcher.dispatch(
            severity="HIGH", title="test", summary="token would leak",
            evidence={"token": "SECRET_ALERT_TOKEN"}, related_entity="x",
        )
        self.assertEqual(len(SpyTransport.sent_messages), 1)
        self.assertNotIn("SECRET_ALERT_TOKEN", SpyTransport.sent_messages[0])
        # title/summary/action columns never contain the secret either
        row = self.db.execute("SELECT title, summary, action_required FROM alerts").fetchone()
        self.assertNotIn("SECRET_ALERT_TOKEN", " ".join(row))

    def test_no_automatic_production_activation(self):
        """The scheduler/CLI must never enable production on their own."""
        from amancore.ops.registry import JobRegistry
        from amancore.config import load_config

        cfg = load_config(ROOT)
        handlers = JobRegistry(self.db, cfg, ROOT).handlers()
        result = handlers["production.check"]({})
        self.assertFalse(result["production_enabled"])
        # and production.yaml still disabled
        self.assertFalse(cfg.production.get("environment", {}).get("production_enabled", False))

    def test_incident_evidence_preserved(self):
        svc = IncidentService(self.db)
        iid = svc.create("security_incident", "CRITICAL", description="breach",
                         evidence={"source": "audit"})
        # evidence is stored and never deleted by status changes
        svc.set_status(iid, "resolved")
        inc = svc.get(iid)
        self.assertIn("source", inc["evidence"])

    def test_dangerous_cli_actions_absent(self):
        """No CLI command enables production, replaces DB, or deletes backups."""
        import amancore.cli as cli

        src = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn("production_enabled = True", src)
        self.assertNotIn("production_enabled=True", src)
        self.assertNotIn("DELETE FROM backups", src)


if __name__ == "__main__":
    unittest.main()
