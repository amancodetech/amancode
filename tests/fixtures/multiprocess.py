"""Multi-Process Test Execution Runner and Lock Diagnostics."""

from __future__ import annotations

import concurrent.futures
import multiprocessing as mp
import os
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def _worker_wrapper(worker_idx: int, fn: Callable[..., T], arg: Any) -> dict[str, Any]:
    """Helper executed inside each separate OS worker process."""
    worker_id = f"worker_{worker_idx:02d}"
    os.environ["TEST_WORKER_ID"] = worker_id
    os.environ["AMANCODE_ISOLATED"] = "1"

    start = time.perf_counter()
    pid = os.getpid()
    try:
        if isinstance(arg, tuple):
            result = fn(*arg)
        elif arg is not None:
            result = fn(arg)
        else:
            result = fn()
        duration = time.perf_counter() - start
        return {
            "worker_id": worker_id,
            "pid": pid,
            "status": "success",
            "result": result,
            "duration": duration,
        }
    except Exception as exc:
        duration = time.perf_counter() - start
        is_lock_error = "database is locked" in str(exc).lower() or "busy" in str(exc).lower()
        return {
            "worker_id": worker_id,
            "pid": pid,
            "status": "error",
            "error_type": type(exc).__name__,
            "error_msg": str(exc),
            "is_lock_error": is_lock_error,
            "duration": duration,
        }


def run_in_processes(
    fn: Callable[..., T],
    items: list[Any],
    workers: int = 4,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Execute worker tasks across multiple isolated OS processes."""
    ctx = mp.get_context("fork" if hasattr(os, "fork") else "spawn")
    results = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
        futures = [
            executor.submit(_worker_wrapper, idx, fn, item)
            for idx, item in enumerate(items, start=1)
        ]
        for f in concurrent.futures.as_completed(futures, timeout=timeout):
            results.append(f.result())

    # Sort results by worker_id for deterministic ordering
    results.sort(key=lambda r: r["worker_id"])
    return results


def capture_sqlite_lock_diagnostics(
    worker_id: str,
    operation: str,
    db_path: str,
    exc: Exception,
) -> dict[str, Any]:
    """Capture structured lock failure diagnostic information."""
    return {
        "worker_id": worker_id,
        "process_id": os.getpid(),
        "operation": operation,
        "database_path": db_path,
        "error_class": type(exc).__name__,
        "error_message": str(exc),
        "busy_timeout_ms": 5000,
        "timestamp": time.time(),
    }
