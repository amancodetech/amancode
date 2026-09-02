"""Deterministic Failure Injection Infrastructure."""

from __future__ import annotations

import threading
from typing import Any


class FailureInjector:
    """Configurable failure injector for simulating system faults."""

    def __init__(self):
        self._failures: dict[str, Any] = {}
        self._fail_once_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def fail(self, target: str, exc: Exception | None = None) -> None:
        """Configure a persistent failure for target."""
        with self._lock:
            self._failures[target] = exc or RuntimeError(f"INJECTED_FAILURE: {target}")

    def fail_once(self, target: str, exc: Exception | None = None) -> None:
        """Configure a single-shot failure for target."""
        with self._lock:
            self._failures[target] = exc or RuntimeError(f"INJECTED_FAILURE_ONCE: {target}")
            self._fail_once_counts[target] = 1

    def check(self, target: str) -> None:
        """Check if a failure is configured for target and raise it if active."""
        with self._lock:
            if target in self._failures:
                exc = self._failures[target]
                if target in self._fail_once_counts:
                    self._fail_once_counts[target] -= 1
                    if self._fail_once_counts[target] <= 0:
                        del self._failures[target]
                        del self._fail_once_counts[target]
                raise exc

    def reset(self) -> None:
        """Reset all configured failures."""
        with self._lock:
            self._failures.clear()
            self._fail_once_counts.clear()


# Default global failure injector for tests
failure_injector = FailureInjector()
