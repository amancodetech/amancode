"""CostGovernor (COST-402 / CO1-CO2) — configurable AI spend protection.

Enforced BEFORE any LLM call. Blocked requests receive deterministic fallbacks,
never another LLM call. All thresholds are configuration, not constants (H5).

Counting model: every draft call consumes 1 LLM-call unit + an estimated token
charge derived from prompt/output characters (~4 chars/token) — message count
alone is not a sufficient cost metric.

State is in-process memory: restart resets windows (documented limitation;
global daily caps are therefore approximate across restarts until persisted).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..log import get_logger

log = get_logger("ops.cost")

DEFAULTS = {
    "enabled": True,
    "per_wa_id_hourly_calls": 10,
    "per_wa_id_daily_calls": 60,
    "global_daily_calls": 5000,
    "daily_token_budget": 400_000,
    "trusted_wa_ids": [],
}


class CostGovernor:
    def __init__(self, config: dict | None = None):
        merged = dict(DEFAULTS)
        merged.update(config or {})
        self.enabled = bool(merged["enabled"])
        self.per_hour = int(merged["per_wa_id_hourly_calls"])
        self.per_day = int(merged["per_wa_id_daily_calls"])
        self.global_daily = int(merged["global_daily_calls"])
        self.token_budget = int(merged["daily_token_budget"])
        self.trusted = {str(w) for w in merged.get("trusted_wa_ids", [])}
        self._calls_by_wa: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._tokens_by_wa: dict[str, float] = defaultdict(float)
        self._global_day: str = time.strftime("%Y-%m-%d", time.gmtime())
        self._global_calls_today = 0
        self._global_tokens_today = 0.0
        self._lock = threading.Lock()

    # ---- internal -------------------------------------------------------
    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._global_day:
            self._global_day = today
            self._global_calls_today = 0
            self._global_tokens_today = 0.0
            self._tokens_by_wa.clear()

    def _prune_window(self, wa_id: str, now: float) -> None:
        q = self._calls_by_wa[wa_id]
        horizon = now - 3600
        while q and (q[0][0] < horizon or q[0][0] < now - 86400):
            q.popleft()

    def _window_counts(self, wa_id: str, now: float) -> tuple[int, int]:
        hour = sum(1 for ts, _ in self._calls_by_wa[wa_id] if ts >= now - 3600)
        day = sum(1 for ts, _ in self._calls_by_wa[wa_id] if ts >= now - 86400)
        return hour, day

    # ---- public API -----------------------------------------------------
    def allow(self, wa_id: str) -> tuple[bool, str]:
        """Decide BEFORE the LLM call. Returns (allowed, reason)."""
        if not self.enabled:
            return True, "disabled"
        wa = str(wa_id)
        if wa in self.trusted:
            return True, "trusted"
        with self._lock:
            self._roll_day()
            now = time.time()
            self._prune_window(wa, now)
            if self._global_calls_today >= self.global_daily:
                return False, "global_daily_calls"
            if self._global_tokens_today >= self.token_budget:
                return False, "global_token_budget"
            hour, day = self._window_counts(wa, now)
            if hour >= self.per_hour:
                return False, "per_wa_hourly"
            if day >= self.per_day:
                return False, "per_wa_daily"
        return True, "ok"

    def record(self, wa_id: str, prompt_chars: int = 0, output_chars: int = 0) -> None:
        """Charge one call AFTER the governor approved it."""
        if not self.enabled:
            return
        wa = str(wa_id)
        est_tokens = (prompt_chars + output_chars) / 4.0
        now = time.time()
        with self._lock:
            self._roll_day()
            self._calls_by_wa[wa].append((now, est_tokens))
            self._tokens_by_wa[wa] += est_tokens
            self._global_calls_today += 1
            self._global_tokens_today += est_tokens

    def snapshot(self) -> dict:
        with self._lock:
            self._roll_day()
            return {
                "day": self._global_day,
                "global_calls_today": self._global_calls_today,
                "global_tokens_today": int(self._global_tokens_today),
                "limits": {
                    "per_wa_id_hourly_calls": self.per_hour,
                    "per_wa_id_daily_calls": self.per_day,
                    "global_daily_calls": self.global_daily,
                    "daily_token_budget": self.token_budget,
                },
                "active_customers": len(self._calls_by_wa),
            }
