"""Scheduler runtime — cron matching + tick + run loop.

Minimal cron (5 fields: minute hour day month weekday) with *, ranges,
lists and step (/n). All schedules from configs/scheduler.yaml.
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timezone

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
    def __init__(self, store: JobStore, runner: JobRunner, config: dict | None = None):
        self.store = store
        self.runner = runner
        self.config = config or {}
        jobs_cfg = self.config.get("jobs", {})
        self.enabled = {}
        self.crons = {}
        for jtype, jconf in jobs_cfg.items():
            if isinstance(jconf, dict):
                self.enabled[jtype] = bool(jconf.get("enabled", False))
                self.crons[jtype] = jconf.get("cron")

    def due_job_types(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        due = []
        for jtype, cron in self.crons.items():
            if cron and cron_matches(cron, now):
                due.append(jtype)
        return due

    def tick(self, worker_id: str = "scheduler", now: datetime | None = None) -> dict:
        """Enqueue due enabled jobs (idempotent per slot). Returns summary."""
        now = now or datetime.now(timezone.utc)
        self.store.requeue_expired_leases(worker_id)
        enqueued: list[str] = []
        skipped: list[str] = []
        for jtype in self.due_job_types(now):
            if not self.enabled.get(jtype, False):
                skipped.append(jtype)
                continue
            slot = now.strftime("%Y-%m-%dT%H:%M")
            job_id = self.store.enqueue(jtype, idempotency_key=f"{jtype}:{slot}")
            enqueued.append(f"{jtype}:{job_id[:8]}")
        return {"enqueued": enqueued, "skipped_disabled": skipped}

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
