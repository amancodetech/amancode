"""TG-304 — Telegram through policy gate, capability gate, cost governor
(Phases 12/13/14/24)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from tests._db import fresh_db, wipe  # noqa: E402

from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.channels.policy import (  # noqa: E402
    ALLOW, DENY, ChannelPolicyEngine,
)
from amancore.channels.router import ChannelRouter  # noqa: E402
from amancore.channels.telegram import MockTelegramProvider, TelegramAdapter  # noqa: E402
from amancore.ops.cost_governor import CostGovernor  # noqa: E402


class FakeBrain:
    def current(self):
        return (1, {})


class PolicyEnablement(unittest.TestCase):
    """Config is the source of truth — disabled channel denies BEFORE provider."""

    def test_disabled_telegram_denies_sends(self):
        p = ChannelPolicyEngine(FakeBrain(), {"telegram": {
            "enabled": False, "customer_messaging": False}})
        self.assertEqual(p.evaluate_send("telegram", "text", "low"), DENY)

    def test_enabled_telegram_allows_low_risk_text(self):
        p = ChannelPolicyEngine(FakeBrain(), {"telegram": {
            "enabled": True, "customer_messaging": True}})
        self.assertEqual(p.evaluate_send("telegram", "text", "low"), ALLOW)

    def test_whatsapp_without_flags_stays_allowed(self):
        p = ChannelPolicyEngine(FakeBrain(), {"whatsapp": {"mode": "mock"}})
        self.assertEqual(p.evaluate_send("whatsapp", "text", "low"), ALLOW)


class WorkerGates(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db(); wipe(self.db)
        self.provider = MockTelegramProvider()
        adapter = TelegramAdapter({"mode": "mock"}, provider=self.provider)
        self.outbox = MessageOutbox(self.db)
        policy = ChannelPolicyEngine(FakeBrain(), {"telegram": {
            "enabled": True, "customer_messaging": True}})
        self.worker = OutboxWorker(
            self.outbox, ChannelRouter({"telegram": adapter}), policy)

    def test_disabled_channel_cancels_before_provider_call(self):
        self.worker.policy = ChannelPolicyEngine(FakeBrain(), {"telegram": {
            "enabled": False, "customer_messaging": False}})
        mid = self.outbox.enqueue("telegram", "777000", "text", {"body": "x"},
                                  idempotency_key="tg-pol-1")
        res = self.worker.process_one(dict(self.outbox.get(mid)))
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["reason"], "policy deny")
        self.assertEqual(self.provider.sent, [])

    def test_outbound_row_is_channel_tagged_and_routes_to_adapter(self):
        mid = self.outbox.enqueue("telegram", "777000", "text",
                                  {"body": "أهلاً"}, idempotency_key="tg-out-1")
        res = self.worker.process_one(dict(self.outbox.get(mid)))
        row = self.outbox.get(mid)
        self.assertEqual(res["status"], "sent")
        self.assertEqual(row["channel"], "telegram")
        self.assertEqual(row["status"], "sent")
        self.assertEqual(len(self.provider.sent), 1)
        self.assertEqual(self.provider.sent[0]["payload"]["text"], "أهلًا"[:0] or "أهلاً")

    def test_unsupported_capability_dies_before_provider_call(self):
        mid = self.outbox.enqueue("telegram", "777000", "video", {"x": 1},
                                  idempotency_key="tg-cap-1")
        res = self.worker.process_one(dict(self.outbox.get(mid)))
        self.assertEqual(res["status"], "failed")
        self.assertTrue(res["reason"].startswith("capability_unsupported"))
        self.assertEqual(self.provider.sent, [])
        self.assertIn("capability_unsupported", self.outbox.get(mid)["failure_reason"])


class GovernorKeys(unittest.TestCase):
    def _gov(self, **kw):
        base = {"per_wa_id_hourly_calls": 2, "per_wa_id_daily_calls": 100,
                "global_daily_calls": 1000, "daily_token_budget": 1_000_000}
        base.update(kw)
        return CostGovernor(base)

    def test_channel_keys_are_isolated_per_identity(self):
        g = self._gov()
        for _ in range(2):
            self.assertTrue(g.allow("telegram:777")[0])
            g.record("telegram:777", 100, 50)
        self.assertFalse(g.allow("telegram:777")[0])   # tg identity exhausted
        self.assertTrue(g.allow("whatsapp:905555")[0])  # WA identity untouched

    def test_global_ceiling_shared_across_channels(self):
        g = self._gov(global_daily_calls=2)
        g.record("telegram:777")
        g.record("whatsapp:888")
        allowed, reason = g.allow("telegram:999")
        self.assertFalse(allowed)
        self.assertEqual(reason, "global_daily_calls")


if __name__ == "__main__":
    unittest.main()
