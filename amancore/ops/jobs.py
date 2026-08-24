"""Job Store + Runner — SQLite-backed operational scheduler.

Safety properties:
  - lease/lock (locked_by + locked_until): no job runs twice concurrently.
  - retry with exponential backoff → max attempts → dead-letter.
  - idempotency_key prevents duplicate enqueues.
  - all retry/timeout settings config-driven (configs/scheduler.yaml).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.jobs")

JOB_STATUSES = {"queued", "running", "completed", "failed", "dead"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class JobStore:
    def __init__(self, db: Database, config: dict | None = None):
        self.db = db
        cfg = config or {}
        retry = cfg.get("retry", {})
        self.max_attempts = int(retry.get("max_attempts", 3))
        self.backoff_seconds = int(retry.get("backoff_seconds", 60))
        self.backoff_factor = float(retry.get("backoff_factor", 2))
        self.timeout_seconds = int(retry.get("timeout_seconds", 300))
        self.lease_seconds = int((cfg.get("scheduler") or {}).get("lease_seconds", 300))

    # ---- enqueue --------------------------------------------------------
    def enqueue(self, type_: str, payload: dict | None = None,
                idempotency_key: str | None = None, run_at: str | None = None) -> str:
        if idempotency_key:
            row = self.db.execute(
                "SELECT job_id FROM jobs WHERE idempotency_key = ? AND status != 'dead'",
                (idempotency_key,),
            ).fetchone()
            if row:
                return row["job_id"]
        job_id = new_id()
        now = _iso(_now())
        self.db.execute(
            "INSERT INTO jobs (job_id, type, payload, status, attempts, next_attempt_at, "
            " idempotency_key, created_at) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)",
            (job_id, type_, json.dumps(payload or {}, ensure_ascii=False),
             run_at or now, idempotency_key, now),
        )
        self.db.commit()
        return job_id

    def get(self, job_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        try:
            job["payload"] = json.loads(job.get("payload") or "{}")
        except (json.JSONDecodeError, TypeError):
            job["payload"] = {}
        return job

    # ---- claim (lease) ---------------------------------------------------
    def claim(self, job_id: str, worker_id: str, lease_seconds: int | None = None) -> bool:
        """Atomically claim a queued job with an expired/absent lease."""
        lease = lease_seconds or self.lease_seconds
        now = _iso(_now())
        until = _iso(_now() + timedelta(seconds=lease))
        cur = self.db.execute(
            "UPDATE jobs SET status = 'running', locked_by = ?, locked_until = ?, "
            " started_at = ? "
            "WHERE job_id = ? AND status = 'queued' "
            "AND (locked_until IS NULL OR locked_until < ?)",
            (worker_id, until, now, job_id, now),
        )
        self.db.commit()
        return cur.rowcount == 1

    def claim_next(self, worker_id: str, limit: int = 5) -> list[dict]:
        """Claim up to `limit` due queued jobs (lease respected)."""
        now = _iso(_now())
        rows = self.db.execute(
            "SELECT job_id FROM jobs WHERE status = 'queued' AND "
            "(next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "AND (locked_until IS NULL OR locked_until < ?) "
            "ORDER BY created_at LIMIT ?",
            (now, now, limit),
        ).fetchall()
        claimed = []
        for r in rows:
            if self.claim(r["job_id"], worker_id):
                claimed.append(self.get(r["job_id"]))
        return claimed

    def requeue_expired_leases(self, worker_id: str = "scheduler",
                               exclude_job_ids: set | None = None) -> int:
        """Reclaim jobs whose lease expired while running (worker crashed).
        CC1: jobs with LIVE zombie threads are excluded — their handler may
        still be writing; freeing the lease would allow parallel execution."""
        now = _iso(_now())
        if exclude_job_ids:
            marks = ",".join("?" * len(exclude_job_ids))
            cur = self.db.execute(
                f"UPDATE jobs SET status = 'queued', locked_by = NULL, locked_until = NULL "
                f"WHERE status = 'running' AND locked_until < ? AND job_id NOT IN ({marks})",
                (now, *exclude_job_ids),
            )
        else:
            cur = self.db.execute(
                "UPDATE jobs SET status = 'queued', locked_by = NULL, locked_until = NULL "
                "WHERE status = 'running' AND locked_until < ?",
                (now,),
            )
        self.db.commit()
        return cur.rowcount

    # ---- terminal states ---------------------------------------------------
    def complete(self, job_id: str, result: dict | None = None) -> None:
        self.db.execute(
            "UPDATE jobs SET status = 'completed', completed_at = ?, error = ? "
            "WHERE job_id = ?",
            (_iso(_now()), json.dumps(result or {}, ensure_ascii=False), job_id),
        )
        self.db.commit()

    def fail(self, job_id: str, error: str, retryable: bool = True) -> str:
        """Increment attempts; retry with backoff or move to dead-letter."""
        job = self.get(job_id)
        attempts = (job or {}).get("attempts", 0) + 1
        if not retryable or attempts >= self.max_attempts:
            self.db.execute(
                "UPDATE jobs SET status = 'dead', attempts = ?, error = ? WHERE job_id = ?",
                (attempts, error, job_id),
            )
            self.db.commit()
            return "dead"
        delay = self.backoff_seconds * (self.backoff_factor ** (attempts - 1))
        next_at = _iso(_now() + timedelta(seconds=delay))
        self.db.execute(
            "UPDATE jobs SET status = 'queued', attempts = ?, error = ?, "
            " locked_by = NULL, locked_until = NULL, next_attempt_at = ? WHERE job_id = ?",
            (attempts, error, next_at, job_id),
        )
        self.db.commit()
        return "queued"

    # ---- queries -----------------------------------------------------------
    def counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}

    def list(self, status: str | None = None, type_: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def dead_letter_count(self) -> int:
        return self.counts().get("dead", 0)


class JobCancelled(Exception):
    """Raised inside a handler when its cancellation token fires (CC1)."""


class JobRunner:
    """Executes a handler for a job with lease + retry semantics."""

    def __init__(self, store: JobStore, handlers: dict, worker_id: str = "worker-1",
                 timeout_seconds: int | None = None):
        self._zombies: dict = {}   # job_id → thread still running past grace
        self.store = store
        self.handlers = handlers
        self.worker_id = worker_id
        self.timeout_seconds = timeout_seconds or store.timeout_seconds

    def run_due(self, limit: int = 5) -> list[dict]:
        results = []
        for job in self.store.claim_next(self.worker_id, limit=limit):
            results.append(self.run_job(job))
        return results

    def run_job(self, job: dict) -> dict:
        handler = self.handlers.get(job["type"])
        if handler is None:
            error = f"no handler for job type {job['type']}"
            self.store.fail(job["job_id"], error, retryable=False)
            return {"job_id": job["job_id"], "status": "dead", "error": error}
        try:
            result = self._run_with_timeout(handler, job["payload"] or {}, job_id=job["job_id"])
            self.store.complete(job["job_id"], result)
            return {"job_id": job["job_id"], "status": "completed", "result": result}
        except Exception as exc:  # noqa: BLE001 — job isolation
            retryable = self._is_retryable(exc)
            status = self.store.fail(job["job_id"], str(exc), retryable=retryable)
            log.warning("job %s (%s) failed: %s (retryable=%s)",
                        job["job_id"], job["type"], exc, retryable)
            return {"job_id": job["job_id"], "status": status, "error": str(exc)}

    def _run_with_timeout(self, handler, payload: dict, job_id: str | None = None) -> dict:
        """CC1: cooperative cancellation — on timeout we signal the worker
        thread and give it a grace period to abort cleanly; a thread that
        survives grace is tracked as a zombie so its expired lease is NOT
        requeued while it still runs (no parallel double-execution)."""
        import threading

        box: dict = {"result": None, "error": None}
        cancel = threading.Event()
        work_payload = dict(payload or {})
        work_payload["_cancel_event"] = cancel   # handlers may check between phases

        def target():
            try:
                box["result"] = handler(work_payload)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(self.timeout_seconds)
        if t.is_alive():
            cancel.set()
            t.join(5.0)  # grace for checkpoint aborts
            if t.is_alive() and job_id:
                self._zombies[job_id] = t
            raise TimeoutError(f"job exceeded timeout {self.timeout_seconds}s")
        if box["error"] is not None:
            raise box["error"]
        return box["result"] or {}

    def zombie_job_ids(self) -> set:
        """CC1: job ids whose worker thread is STILL alive past its grace."""
        alive = {jid for jid, t in self._zombies.items() if t.is_alive()}
        for jid in set(self._zombies) - alive:
            del self._zombies[jid]      # finished zombies stop blocking requeue
        return alive

    def _is_retryable(self, exc: Exception) -> bool:
        name = type(exc).__name__
        retryable = {
            "OperationalError", "TimeoutError", "ConnectionError", "ConnectionRefusedError",
            "requests.ConnectionError", "requests.Timeout", "JobCancelled",
        }
        return name in retryable or any(k in name for k in ("Timeout", "Connection"))
