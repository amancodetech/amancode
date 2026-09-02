"""Real Multithreaded Concurrency Runner for Database & RIL Race-Condition Testing."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def run_concurrently(
    fn: Callable[..., T],
    items: list[Any],
    workers: int = 4,
) -> list[T]:
    """Execute a function across a thread pool with the specified concurrency."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fn, item) if not isinstance(item, tuple) else executor.submit(fn, *item) for item in items]
        return [f.result() for f in futures]
