"""Process-Safe & Deterministic Test Identifier Generator."""

from __future__ import annotations

import os
import threading


class DeterministicIDGenerator:
    """Thread-safe and process-safe deterministic sequential ID generator for tests."""

    def __init__(self, prefix_tag: str = "test", worker_id: str | None = None):
        self.prefix_tag = prefix_tag
        self._worker_id = worker_id
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def worker_id(self) -> str:
        if self._worker_id:
            return self._worker_id
        env_worker = os.environ.get("TEST_WORKER_ID") or os.environ.get("PYTEST_XDIST_WORKER")
        return env_worker or "p0"

    def next(self, entity_type: str) -> str:
        """Generate next deterministic ID for the given entity type, namespaced per worker."""
        clean_type = entity_type.lower().strip()
        with self._lock:
            val = self._counters.get(clean_type, 0) + 1
            self._counters[clean_type] = val
            w_tag = self.worker_id
            if w_tag == "p0" or not w_tag:
                return f"{clean_type}-{self.prefix_tag}-{val:04d}"
            return f"{clean_type}-{w_tag}-{self.prefix_tag}-{val:04d}"

    def reset(self) -> None:
        """Reset all internal counters."""
        with self._lock:
            self._counters.clear()

    def scoped(self, tag: str) -> DeterministicIDGenerator:
        """Create a child scoped generator with a custom tag."""
        return DeterministicIDGenerator(prefix_tag=tag, worker_id=self._worker_id)

    def for_worker(self, worker_id: str) -> DeterministicIDGenerator:
        """Create an isolated generator bound to a specific worker namespace."""
        return DeterministicIDGenerator(prefix_tag=self.prefix_tag, worker_id=worker_id)


# Default global instance for tests
ids = DeterministicIDGenerator()
