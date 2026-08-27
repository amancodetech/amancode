"""TG-302 — Telegram error taxonomy through the generic Outbox (Phases 11/24)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from tests._db import fresh_db, wipe  # noqa: E402

from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.channels.router import ChannelRouter  # noqa: E402
from amancore.channels.telegram import (  # noqa: E402
    TelegramAPIError, TelegramAdapter, classify_telegram_error,
)


class AllowPolicy:
    def evaluate_send(self, channel, message_type, risk_level=""):
        return "allow"

    def opt_out_blocks_marketing(self, channel):
        return True


def classify_cases():
    return [
        # (status, description, retry_after, expected_category)
        (401, "Unauthorized", None, "auth"),
        (403, "Forbidden: bot was blocked by the user", None, "bad_recipient"),
        (400, "Bad Request: chat not found", None, "bad_recipient"),
        (400, "Bad Request: user deactivated", None, "bad_recipient"),
        (429, "Too Many Requests: retry after 9", 9, "rate_limited"),
        (500, "Internal Server Error", None, "provider"),
        (502, "Bad Gateway", None, "provider"),
        (400, "Bad Request: message text is empty", None, "provider"),
    ]


class TaxonomyTable(unittest.TestCase):
    def test_official_error_codes_map_to_retry_categories(self):
        for status, desc, wait, expected in classify_cases():
            err = classify_telegram_error(status, desc, wait)
            self.assertEqual(err.category, expected, f"{status}: {desc}")
            self.assertEqual(err.http_status, status)

    def test_rate_limit_honors_retry_after(self):
        err = classify_telegram_error(429, "Too Many Requests", 42)
        self.assertEqual(err.retry_after_seconds, 42)

    def test_adapter_classify_passthrough(self):
        a = TelegramAdapter({"mode": "mock"})
        cat, wait = a.classify_error(classify_telegram_error(429, "", 30))
        self.assertEqual((cat, wait), ("rate_limited", 30))
        self.assertEqual(a.classify_error(RuntimeError("x")), (None, None))


class _FailingProvider:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def send(self, recipient, payload):
        self.calls += 1
        raise self.exc


class OutboxRetrySemantics(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        wipe(self.db)

    def tearDown(self):
        pass  # shared fixture db

    def _worker_with(self, provider):
        adapter = TelegramAdapter({"mode": "mock"}, provider=provider)
        router = ChannelRouter({"telegram": adapter})
        outbox = MessageOutbox(self.db)
        worker = OutboxWorker(outbox, router, AllowPolicy())
        return outbox, worker

    def test_auth_failure_dead_letters_without_retry(self):
        outbox, worker = self._worker_with(_FailingProvider(
            classify_telegram_error(401, "Unauthorized")))
        mid = outbox.enqueue("telegram", "777000", "text", {"body": "hi"},
                             idempotency_key="tg-err-1")
        res = worker.process_one(dict(outbox.get(mid)))
        row = outbox.get(mid)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(row["status"], "dead")

    def test_bad_recipient_dead_letters(self):
        outbox, worker = self._worker_with(_FailingProvider(
            classify_telegram_error(400, "Bad Request: chat not found")))
        mid = outbox.enqueue("telegram", "-1", "text", {"body": "hi"},
                             idempotency_key="tg-err-2")
        worker.process_one(dict(outbox.get(mid)))
        self.assertEqual(outbox.get(mid)["status"], "dead")

    def test_rate_limited_schedules_honored_wait(self):
        outbox, worker = self._worker_with(_FailingProvider(
            classify_telegram_error(429, "Too Many Requests", 120)))
        mid = outbox.enqueue("telegram", "777000", "text", {"body": "hi"},
                             idempotency_key="tg-err-3")
        res = worker.process_one(dict(outbox.get(mid)))
        row = outbox.get(mid)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(row["status"], "queued")   # retried, not dead
        self.assertIsNotNone(row["next_attempt_at"])
        self.assertIn("[rate_limited]", row["failure_reason"])

    def test_provider_5xx_retries_with_backoff(self):
        outbox, worker = self._worker_with(_FailingProvider(
            classify_telegram_error(500, "Internal Server Error")))
        mid = outbox.enqueue("telegram", "777000", "text", {"body": "hi"},
                             idempotency_key="tg-err-4")
        worker.process_one(dict(outbox.get(mid)))
        row = outbox.get(mid)
        self.assertEqual(row["status"], "queued")
        self.assertIn("[provider]", row["failure_reason"])


if __name__ == "__main__":
    unittest.main()
