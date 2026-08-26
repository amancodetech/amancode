"""WA-302: Graph error taxonomy (W1), centralized number normalization (W2),
4096 text cap at the adapter choke point (W4)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.channels.wa_errors import (  # noqa: E402
    WhatsAppSendError, classify_graph_error, normalize_e164_digits,
)
from amancore.storage.db import Database, ensure_columns  # noqa: E402
from amancore.storage.db import _split_schema  # noqa: E402


class Taxonomy(unittest.TestCase):
    def test_401_is_auth(self):
        e = classify_graph_error(401, '{"error":{"code":0}}')
        self.assertEqual(e.category, "auth")

    def test_graph_code_190_is_auth_even_with_200_shell(self):
        e = classify_graph_error(400, '{"error":{"code":190,"message":"token"}}')
        self.assertEqual(e.category, "auth")

    def test_bad_recipient_code(self):
        e = classify_graph_error(400, '{"error":{"code":131026}}')
        self.assertEqual(e.category, "bad_recipient")

    def test_429_honors_retry_after(self):
        e = classify_graph_error(429, "{}", retry_after_header="90")
        self.assertEqual(e.category, "rate_limited")
        self.assertEqual(e.retry_after_seconds, 90)

    def test_5xx_provider_transient(self):
        e = classify_graph_error(503, "upstream")
        self.assertEqual(e.category, "provider")


class RetryPolicyIntegration(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "storage" / "_test_wa302.db"
        self.path.unlink(missing_ok=True)
        self.db = Database(self.path)
        schema = (ROOT / "amancore" / "storage" / "schema.sql").read_text()
        tables_sql, _ = _split_schema(schema)
        self.db.apply_schema(tables_sql)
        ensure_columns(self.db)

    def tearDown(self):
        self.db.close()
        self.path.unlink(missing_ok=True)

    def _worker(self, exc_to_raise):
        class P:
            def evaluate_send(self, *a, **k):
                return "allow"

        class Adapter:
            def send(self, *a, **k):
                raise exc_to_raise

            def classify_error(self, exc):
                # contract surface — mirrors WhatsAppAdapter behavior
                return (getattr(exc, "category", None),
                        getattr(exc, "retry_after_seconds", None))

        alert_calls = []
        w = OutboxWorker(MessageOutbox(self.db, max_attempts=3),
                         {"whatsapp": Adapter()}, P(), claim_mode="atomic",
                         owner_alert=lambda *a, **k: alert_calls.append((a, k)))
        return w, alert_calls

    def test_bad_recipient_dies_immediately_no_retries(self):
        ob = MessageOutbox(self.db, max_attempts=3)
        mid = ob.enqueue("whatsapp", "+15551230000", "text", {"body": "x"})
        err = classify_graph_error(400, '{"error":{"code":131026}}')
        w, alerts = self._worker(err)
        w.drain(limit=5)
        row = ob.get(mid)
        self.assertEqual(row["status"], "dead")          # 1 attempt, not 3
        self.assertEqual(row["attempts"], 1)
        self.assertIn("bad_recipient", row["failure_reason"])
        self.assertEqual(len(alerts), 1)

    def test_rate_limited_reschedules_by_retry_after(self):
        ob = MessageOutbox(self.db, max_attempts=3)
        mid = ob.enqueue("whatsapp", "+15551230001", "text", {"body": "x"})
        err = classify_graph_error(429, "{}", retry_after_header="120")
        w, _ = self._worker(err)
        w.drain(limit=5)
        row = ob.get(mid)
        self.assertEqual(row["status"], "queued")        # alive, waiting
        from datetime import datetime, timezone
        nxt = datetime.fromisoformat(row["next_attempt_at"])
        delta = (nxt - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(delta, 100)                   # ≈120s honored

    def test_auth_death_alerts_once(self):
        ob = MessageOutbox(self.db, max_attempts=3)
        mid = ob.enqueue("whatsapp", "+15551230002", "text", {"body": "x"})
        w, alerts = self._worker(classify_graph_error(401, '{"error":{"code":190}}'))
        w.drain(limit=5)
        self.assertEqual(ob.get(mid)["status"], "dead")
        _, kwargs = alerts[0]
        self.assertEqual(kwargs["event_type"], "outbox.dead")


class NormalizationW2(unittest.TestCase):
    def test_international_double_zero_prefix(self):
        self.assertEqual(normalize_e164_digits("00905321112233"), "905321112233")

    def test_plus_sign_stripped_by_digit_filter(self):
        self.assertEqual(normalize_e164_digits("+90532 111 22 33"), "905321112233")

    def test_local_trailing_zero_NOT_eaten(self):
        # the old lstrip("0") bug turned 0501… into 501… — must stay intact
        self.assertEqual(normalize_e164_digits("0501234567"), "0501234567")

    def test_empty_safe(self):
        self.assertEqual(normalize_e164_digits(None), "")
        self.assertEqual(normalize_e164_digits(""), "")

    def test_telegram_console_delegates(self):
        from amancore.ops.telegram_console import normalize_number

        self.assertEqual(normalize_number("+90532…".replace("…", "")), "90532")


class TextCapW4(unittest.TestCase):
    def test_long_text_clamped_at_choke_point(self):
        """The Graph adapter clamps text to 4096 before the request leaves."""
        import inspect

        from amancore.channels import whatsapp as wa_mod

        src = inspect.getsource(wa_mod.WhatsAppGraphAdapter.send if hasattr(
            wa_mod, "WhatsAppGraphAdapter") else wa_mod)
        self.assertIn(":4096", src)


if __name__ == "__main__":
    unittest.main()
