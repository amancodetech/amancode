import unittest

from amancore.ops.alerts import (
    AlertDispatcher,
    AlertStore,
    EmailAlertTransport,
    LogAlertTransport,
    TelegramAlertTransport,
    resolve_transport,
    transport_status,
)
from tests.common import TempDirTestCase, make_db

ALERT_CFG = {
    "channel": "log",
    "dedup_cooldown_minutes": 60,
    "dedup_window_hours": 24,
    "telegram_bot_token_env": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
}


class TransportResolveTest(unittest.TestCase):
    def test_log_fallback_by_default(self):
        transport = resolve_transport(ALERT_CFG, env={})
        self.assertIsInstance(transport, LogAlertTransport)

    def test_telegram_when_configured(self):
        transport = resolve_transport({"channel": "telegram"}, env={
            "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42",
        })
        self.assertIsInstance(transport, TelegramAlertTransport)

    def test_email_when_configured(self):
        transport = resolve_transport({"channel": "email"}, env={
            "SMTP_HOST": "smtp.example.com", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
            "SMTP_TO": "o@example.com",
        })
        self.assertIsInstance(transport, EmailAlertTransport)

    def test_channel_configured_but_no_creds_falls_back(self):
        transport = resolve_transport({"channel": "telegram"}, env={})
        self.assertIsInstance(transport, LogAlertTransport)

    def test_status(self):
        self.assertEqual(transport_status(ALERT_CFG, env={}), "log (fallback)")
        self.assertEqual(transport_status({"channel": "telegram"}, env={}), "NOT_CONFIGURED")
        self.assertEqual(transport_status({"channel": "telegram"}, env={
            "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), "telegram (available)")


class AlertDispatcherTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.dispatcher = AlertDispatcher(self.db, config=ALERT_CFG)
        self.store = AlertStore(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_low_logged_not_delivered(self):
        result = self.dispatcher.dispatch(
            severity="LOW", title="info", summary="x",
        )
        self.assertFalse(result["delivered"])
        self.assertEqual(self.store.list()[0]["severity"], "LOW")

    def test_high_logged_to_owner_sink(self):
        result = self.dispatcher.dispatch(
            severity="HIGH", title="something happened", summary="details",
            action_required="review", related_entity="lead-1",
        )
        self.assertTrue(result["delivered"])
        self.assertEqual(result["transport"], "log")

    def test_dedup_within_cooldown(self):
        first = self.dispatcher.dispatch(
            severity="HIGH", title="spike", summary="x", fingerprint="fp:1",
        )
        second = self.dispatcher.dispatch(
            severity="HIGH", title="spike again", summary="x", fingerprint="fp:1",
        )
        self.assertTrue(second["deduplicated"])
        self.assertFalse(second["delivered"])
        self.assertEqual(len(self.store.list()), 1)

    def test_different_fingerprint_no_dedup(self):
        self.dispatcher.dispatch(severity="HIGH", title="a", fingerprint="f1")
        self.dispatcher.dispatch(severity="HIGH", title="b", fingerprint="f2")
        self.assertEqual(len(self.store.list()), 2)

    def test_invalid_severity(self):
        with self.assertRaises(ValueError):
            self.dispatcher.dispatch(severity="URGENT", title="x")

    def test_counts(self):
        self.dispatcher.dispatch(severity="HIGH", title="a")
        self.dispatcher.dispatch(severity="LOW", title="b")
        counts = self.store.counts()
        self.assertEqual(counts.get("HIGH"), 1)
        self.assertEqual(counts.get("LOW"), 1)


if __name__ == "__main__":
    unittest.main()
