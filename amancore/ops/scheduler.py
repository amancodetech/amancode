"""Scheduler runtime — cron matching + tick + run loop.

Minimal cron (5 fields: minute hour day month weekday) with *, ranges,
lists and step (/n). All schedules from configs/scheduler.yaml.
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timedelta, timezone

from ..log import get_logger
from .jobs import JobRunner, JobStore

log = get_logger("ops.scheduler")


def _field_matches(expr: str, value: int) -> bool:
    if expr == "*":
        return True
    for part in expr.split(","):
        part = part.strip()
        if "/" in part:
            base_raw, step = part.split("/")
            base = 0 if base_raw in ("*", "") else int(base_raw)
            if value >= base and (value - base) % int(step) == 0:
                return True
        elif "-" in part:
            lo, hi = (int(x) for x in part.split("-"))
            if lo <= value <= hi:
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def _business_tz(tz_name: str | None):
    """CC5: honor configured business timezone (scheduler.yaml timezone:)."""
    if not tz_name:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — unknown tz falls back to UTC loudly
        from ..log import get_logger

        get_logger("ops.scheduler").warning("unknown timezone %s — using UTC", tz_name)
        return timezone.utc


def cron_matches(expr: str, now: datetime | None = None) -> bool:
    """Match a 5-field cron expression against `now` (UTC by default)."""
    now = now or datetime.now(timezone.utc)
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    return (
        _field_matches(minute, now.minute)
        and _field_matches(hour, now.hour)
        and _field_matches(dom, now.day)
        and _field_matches(month, now.month)
        and _field_matches(dow, now.weekday())  # 0=Monday .. 6=Sunday
    )


class SchedulerRuntime:
    CATCHUP_MINUTES_DEFAULT = 60  # restart gaps shorter than this still fire

    def __init__(self, store: JobStore, runner: JobRunner, config: dict | None = None):
        self.store = store
        self.runner = runner
        self.config = config or {}
        self.tz = _business_tz(self.config.get("timezone"))
        try:
            self.catchup_minutes = max(0, int(self.config.get("catchup_minutes",
                                       self.CATCHUP_MINUTES_DEFAULT)))
        except (TypeError, ValueError):
            self.catchup_minutes = self.CATCHUP_MINUTES_DEFAULT
        self._last_tick: datetime | None = None   # in-memory continuity marker
        jobs_cfg = self.config.get("jobs", {})
        self.enabled = {}
        self.crons = {}
        for jtype, jconf in jobs_cfg.items():
            if isinstance(jconf, dict):
                self.enabled[jtype] = bool(jconf.get("enabled", False))
                self.crons[jtype] = jconf.get("cron")

    def db_ok(self, idempotency_key: str) -> bool:
        row = self.store.db.execute(
            "SELECT 1 FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return row is not None

    def due_job_types(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        due = []
        for jtype, cron in self.crons.items():
            if cron and cron_matches(cron, now):
                due.append(jtype)
        return due

    def tick(self, worker_id: str = "scheduler", now: datetime | None = None) -> dict:
        """Enqueue due enabled jobs. CC5: evaluated in the business timezone,
        with a catch-up sweep over missed minutes (restart/downtime gaps) —
        slot idempotency keys keep every backfilled slot firing exactly once."""
        now = now or datetime.now(self.tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.tz)
        exclude = self.runner.zombie_job_ids() if self.runner is not None else None
        self.store.requeue_expired_leases(worker_id, exclude_job_ids=exclude)
        enqueued: list[str] = []
        skipped: list[str] = []
        # CC5 catch-up window: everything since the LAST tick (capped), so a
        # healthy every-minute cron still fires exactly once per minute, and a
        # restart gap backfills each missed slot once (idempotency keys dedupe).
        first_tick = self._last_tick is None
        if first_tick or now <= self._last_tick:
            start = now
        else:
            start = max(now - timedelta(minutes=self.catchup_minutes),
                        self._last_tick + timedelta(minutes=1))
        minutes = [start + timedelta(minutes=i) for i in range(0, 10000)]
        minutes = [m for m in minutes if m <= now]
        if now not in minutes:
            minutes.append(now)
        self._last_tick = now
        for slot_dt in minutes:
            local_dt = slot_dt.astimezone(self.tz)
            for jtype in self.due_job_types(local_dt):
                if not self.enabled.get(jtype, False):
                    skipped.append(jtype)
                    continue
                slot = local_dt.strftime("%Y-%m-%dT%H:%M")
                key = f"{jtype}:{slot}"
                exists = self.db_ok(key)
                if exists:
                    continue  # backfill slot already has a live/completed job
                job_id = self.store.enqueue(jtype, idempotency_key=key)
                enqueued.append(f"{jtype}:{job_id[:8]}")
        return {"enqueued": sorted(set(enqueued)), "skipped_disabled": sorted(set(skipped))}

    def run_once(self, worker_id: str = "scheduler", limit: int = 10) -> dict:
        """One pass: enqueue due + execute queued jobs. Returns summary."""
        tick = self.tick(worker_id)
        results = self.runner.run_due(limit=limit)
        return {
            "tick": tick,
            "executed": [r["job_id"][:8] for r in results],
            "completed": sum(1 for r in results if r["status"] == "completed"),
            "failed": sum(1 for r in results if r["status"] in ("failed", "dead")),
            "details": results,
        }

    def run_loop(self, interval_seconds: int | None = None, max_iterations: int | None = None) -> None:
        interval = (
            int(self.config.get("scheduler", {}).get("poll_interval_seconds", 30))
            if interval_seconds is None else interval_seconds
        )
        stop = {"requested": False}

        def _handle(signum, frame):  # noqa: ARG001 — signal handler signature
            log.info("scheduler received signal %s — graceful shutdown", signum)
            stop["requested"] = True

        previous_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                previous_handlers[sig] = signal.signal(sig, _handle)
            except ValueError:  # not in main thread (e.g. tests)
                pass
        iterations = 0
        try:
            while max_iterations is None or iterations < max_iterations:
                if stop["requested"]:
                    log.info("scheduler stopped gracefully after %s iterations", iterations)
                    break
                try:
                    self.run_once()
                except Exception as exc:  # noqa: BLE001 — loop must survive
                    log.error("scheduler iteration failed: %s", exc)
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                # sleep in small slices so signals interrupt promptly
                slept = 0.0
                while slept < interval and not stop["requested"]:
                    time.sleep(min(1.0, interval - slept))
                    slept += 1.0
        finally:
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except ValueError:
                    pass
