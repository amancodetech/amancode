"""Deterministic Clock Abstraction for Tests."""

from __future__ import annotations

import datetime
from typing import Any


class DeterministicClock:
    """Deterministic, controllable clock for time-sensitive tests."""

    def __init__(self, initial_iso: str = "2026-09-02T12:00:00+00:00"):
        self._current_time = datetime.datetime.fromisoformat(initial_iso)

    def freeze(self, target: str | datetime.datetime) -> None:
        """Freeze clock at a specific timestamp."""
        if isinstance(target, str):
            self._current_time = datetime.datetime.fromisoformat(target)
        else:
            self._current_time = target

    def advance(self, seconds: float = 1.0) -> None:
        """Advance the clock forward by the given number of seconds."""
        self._current_time += datetime.timedelta(seconds=seconds)

    def now(self) -> datetime.datetime:
        """Return the current frozen datetime object."""
        return self._current_time

    def now_iso(self) -> str:
        """Return ISO-8601 formatted string."""
        return self._current_time.isoformat()

    def reset(self, initial_iso: str = "2026-09-02T12:00:00+00:00") -> None:
        """Reset clock back to initial timestamp."""
        self._current_time = datetime.datetime.fromisoformat(initial_iso)


# Default global clock instance
clock = DeterministicClock()
