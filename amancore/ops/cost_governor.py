"""CostGovernor (COST-402 / CO1-CO2) — configurable AI spend protection.

Enforced BEFORE any LLM call. Blocked requests receive deterministic fallbacks,
never another LLM call. All thresholds are configuration, not constants (H5).

Counting model: every draft call consumes 1 LLM-call unit + an estimated token
charge derived from prompt/output characters (~4 chars/token) — message count
alone is not a sufficient cost metric.

Keys are CHANNEL-NEUTRAL opaque identity strings ("{channel}:{external_user_id}").
Daily per-key and global counters are PERSISTED in the cost_counters table
(UPSERT, multi-process safe); hourly windows remain in-process by design
(restart resets hourly precision only — documented tradeoff).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..log import get_logger

log = get_logger("ops.cost")

DEFAULTS = {
    "enabled": True,
    "per_identity_hourly_calls": 10,   # legacy key: per_wa_id_hourly_calls
    "per_identity_daily_calls": 60,    # legacy key: per_wa_id_daily_calls
    "global_daily_calls": 5000,
    "daily_token_budget": 400_000,
    "trusted_identities": [],          # legacy key: trusted_wa_ids
}


class CostGovernor:
    #: legacy config keys (documented aliases) normalize onto canonical names
    _LEGACY_ALIASES = {
        "per_wa_id_hourly_calls": "per_identity_hourly_calls",
        "per_wa_id_daily_calls": "per_identity_daily_calls",
        "trusted_wa_ids": "trusted_identities",
    }

    def __init__(self, config: dict | None = None, db=None):
        cfg = dict(config or {})
        for old, new in self._LEGACY_ALIASES.items():
            if old in cfg and new not in cfg:
                cfg[new] = cfg.pop(old)
            else:
                cfg.pop(old, None)
        merged = dict(DEFAULTS)
        merged.update(cfg)
        self.enabled = bool(merged["enabled"])
        self.per_hour = int(merged["per_identity_hourly_calls"])
        self.per_day = int(merged["per_identity_daily_calls"])
        self.global_daily = int(merged["global_daily_calls"])
        self.token_budget = int(merged["daily_token_budget"])
        self.trusted = {str(w) for w in merged.get("trusted_identities", []) or []}
        self.db = db
        self._calls_by_key: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._tokens_by_key: dict[str, float] = defaultdict(float)
        self._global_day: str = time.strftime("%Y-%m-%d", time.gmtime())
        self._global_calls_today = 0
        self._global_tokens_today = 0.0
        self._lock = threading.Lock()
        if db is not None:
            self._ensure_table()

    # ---- persistence -----------------------------------------------------
    def _ensure_table(self) -> None:
        try:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS cost_counters ("
                " day TEXT NOT NULL, key TEXT NOT NULL,"
                " calls INTEGER NOT NULL DEFAULT 0, tokens REAL NOT NULL DEFAULT 0,"
                " PRIMARY KEY(day, key))")
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 — governor must never block startup
            log.error("cost_counters init failed: %s", exc)
            self.db = None

    def _persisted_daily(self, key: str | None, today: str) -> tuple[int, float]:
        """Read persisted counters; key=None → global totals for today."""
        if self.db is None:
            return (self._global_calls_today, self._global_tokens_today) \
                if key is None else (0, 0.0)
        try:
            if key is None:
                row = self.db.execute(
                    "SELECT COALESCE(SUM(calls),0) c, COALESCE(SUM(tokens),0) t"
                    " FROM cost_counters WHERE day=?", (today,)).fetchone()
            else:
                row = self.db.execute(
                    "SELECT calls c, tokens t FROM cost_counters WHERE day=? AND key=?",
                    (today, key)).fetchone()
            return int(row["c"] or 0), float(row["t"] or 0)
        except Exception:  # noqa: BLE001
            return 0, 0.0

    def _persist_charge(self, key: str, est_tokens: float, today: str,
                        global_calls: int, global_tokens: float) -> None:
        if self.db is None:
            return
        try:
            self.db.execute(
                "INSERT INTO cost_counters (day, key, calls, tokens) VALUES (?, ?, 1, ?)"
                " ON CONFLICT(day, key) DO UPDATE SET"
                " calls = calls + 1, tokens = tokens + excluded.tokens",
                (today, key, est_tokens))
            self.db.execute(
                "INSERT INTO cost_counters (day, key, calls, tokens)"
                " VALUES (?, '__global__', ?, ?)"
                " ON CONFLICT(day, key) DO UPDATE SET"
                " calls = excluded.calls, tokens = excluded.tokens",
                (today, global_calls, global_tokens))
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 — accounting failure never blocks replies
            log.error("cost.persist failed: %s", exc)

    # ---- internal -------------------------------------------------------
    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._global_day:
            self._global_day = today
            self._global_calls_today = 0
            self._global_tokens_today = 0.0
            self._tokens_by_key.clear()

    def _prune_window(self, key: str, now: float) -> None:
        q = self._calls_by_key[key]
        horizon = now - 3600
        while q and (q[0][0] < horizon or q[0][0] < now - 86400):
            q.popleft()

    def _window_counts(self, key: str, now: float) -> tuple[int, int]:
        hour = sum(1 for ts, _ in self._calls_by_key[key] if ts >= now - 3600)
        day = sum(1 for ts, _ in self._calls_by_key[key] if ts >= now - 86400)
        return hour, day

    # ---- public API -----------------------------------------------------
    def allow(self, key: str) -> tuple[bool, str]:
        """Decide BEFORE the LLM call. Returns (allowed, reason).

        `key` is an opaque channel-neutral identity string."""
        if not self.enabled:
            return True, "disabled"
        key = str(key)
        if key in self.trusted:
            return True, "trusted"
        with self._lock:
            self._roll_day()
            now = time.time()
            self._prune_window(key, now)
            g_calls, g_tokens = self._persisted_daily(None, self._global_day)
            if g_calls >= self.global_daily:
                return False, "global_daily_calls"
            if g_tokens >= self.token_budget:
                return False, "global_token_budget"
            hour, day = self._window_counts(key, now)
            p_calls, _ = self._persisted_daily(key, self._global_day)
            if hour >= self.per_hour:
                return False, "per_identity_hourly"
            if max(day, p_calls) >= self.per_day:
                return False, "per_identity_daily"
        return True, "ok"

    def record(self, key: str, prompt_chars: int = 0, output_chars: int = 0) -> None:
        """Charge one call AFTER the governor approved it."""
        if not self.enabled:
            return
        key = str(key)
        est_tokens = (prompt_chars + output_chars) / 4.0
        now = time.time()
        with self._lock:
            self._roll_day()
            self._calls_by_key[key].append((now, est_tokens))
            self._tokens_by_key[key] += est_tokens
            self._global_calls_today += 1
            self._global_tokens_today += est_tokens
            self._persist_charge(key, est_tokens, self._global_day,
                                 self._global_calls_today, self._global_tokens_today)

    def snapshot(self) -> dict:
        with self._lock:
            self._roll_day()
            g_calls, g_tokens = self._persisted_daily(None, self._global_day)
            return {
                "day": self._global_day,
                "global_calls_today": max(g_calls, self._global_calls_today),
                "global_tokens_today": int(max(g_tokens, self._global_tokens_today)),
                "limits": {
                    "per_identity_hourly_calls": self.per_hour,
                    "per_identity_daily_calls": self.per_day,
                    "global_daily_calls": self.global_daily,
                    "daily_token_budget": self.token_budget,
                },
                "active_identities": len(self._calls_by_key),
                "persistent": self.db is not None,
            }
