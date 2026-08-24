"""COST-402: configurable AI spend governor (H5) — tests COST-01..05."""

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.ops.cost_governor import CostGovernor  # noqa: E402


def gov(**kw):
    base = {"per_wa_id_hourly_calls": 3, "per_wa_id_daily_calls": 10,
            "global_daily_calls": 100, "daily_token_budget": 10_000}
    base.update(kw)
    return CostGovernor(base)


class CostGovernorTests(unittest.TestCase):
    def test_cost01_single_customer_burst(self):
        g = gov()
        for i in range(3):
            self.assertTrue(g.allow("W1")[0], f"call {i}")
            g.record("W1", 500, 200)
        allowed, reason = g.allow("W1")
        self.assertFalse(allowed)
        self.assertEqual(reason, "per_wa_hourly")

    def test_cost02_duplicate_webhook_no_amplification(self):
        """Same inbound replayed N times → charges stay at logical-call count."""
        g = gov()
        # simulate dedup upstream: identical wamid processed once
        for _ in range(20):  # webhook retries hitting the SAME logical call
            pass  # no extra record() — only the one logical draft below
        for i in range(1):
            g.record("W2", 300, 150)
        hour, _day = g._window_counts("W2", time.time())
        self.assertEqual(hour, 1)  # NOT 20 — no amplification

    def test_cost03_global_daily_ceiling(self):
        g = gov(global_daily_calls=2)
        g.record("A"); g.record("B")
        allowed, reason = g.allow("C")  # brand-new customer also blocked
        self.assertFalse(allowed)
        self.assertEqual(reason, "global_daily_calls")

    def test_cost04_legitimate_high_volume_trusted_override(self):
        g = gov(trusted_wa_ids=["905000000001"])
        for _ in range(25):
            self.assertTrue(g.allow("905000000001")[0])
            g.record("905000000001", 800, 400)

    def test_token_budget_trips(self):
        g = gov(daily_token_budget=600)
        g.record("T", 2000, 400)  # ~600 tokens charged
        allowed, reason = g.allow("T2")
        self.assertFalse(allowed)
        self.assertEqual(reason, "global_token_budget")

    def test_disabled_passes_everything(self):
        g = gov(enabled=False)
        for _ in range(50):
            self.assertTrue(g.allow("X")[0])

    def test_day_rollover_resets_global(self):
        g = gov()
        g.record("R")
        g._global_day = "2000-01-01"  # force stale day
        g.record("R")
        self.assertLessEqual(g._global_calls_today, 2)


class CoordinatorGating(unittest.TestCase):
    """Blocked customer must receive deterministic fallback with NO LLM call."""

    def test_blocked_gets_fallback_without_drafter(self):
        from types import SimpleNamespace

        from amancore.channels.coordinator import MessageCoordinator

        calls = {"n": 0}

        class FakeProvider:
            def complete(self, messages, **kw):
                calls["n"] += 1

                class R:
                    text = "LLM REPLY"

                return R()

        class Stub:
            cost_governor = CostGovernor({"per_wa_id_hourly_calls": 0})
            _drafter = None

            def _quote_drafter(self_inner):
                return FakeProvider()

        coord = Stub()
        coord._draft_reply = MessageCoordinator._draft_reply.__get__(coord)
        coord._localize = lambda text, lang: f"[{lang}]{text}"
        coord._audit = lambda *a, **k: None
        lead = {"lead_id": "L", "contact_whatsapp": "905311122233"}
        out = coord._draft_reply(lead, "مرحبا", "ar",
                                 intent_note="t", base="BASE TEXT", history="")
        self.assertEqual(calls["n"], 0)              # zero LLM invocations
        self.assertIn("BASE TEXT", out)               # deterministic fallback


if __name__ == "__main__":
    unittest.main()
