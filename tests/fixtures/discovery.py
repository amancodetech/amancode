"""Safe Discovery and Stopping Protocol State Machine and Guard Framework."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

log = logging.getLogger("amancore.testing.discovery")


class DiscoveryState(str, Enum):
    INITIALIZED = "INITIALIZED"
    SAFETY_CHECKED = "SAFETY_CHECKED"
    DISCOVERING = "DISCOVERING"
    VALIDATING = "VALIDATING"
    CHECKPOINT = "CHECKPOINT"
    EXPAND = "EXPAND"
    COMPLETED = "COMPLETED"
    STOPPED_SAFELY = "STOPPED_SAFELY"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


class FailureClassification(str, Enum):
    RELEASE_BLOCKER = "RELEASE_BLOCKER"
    TEST_INFRASTRUCTURE_FAILURE = "TEST_INFRASTRUCTURE_FAILURE"
    EXPECTED_CONTENTION = "EXPECTED_CONTENTION"
    ENVIRONMENT_LIMITATION = "ENVIRONMENT_LIMITATION"
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    TEST_FLAKINESS = "TEST_FLAKINESS"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class DiscoveryLimits:
    max_workers: int = 8
    max_runtime_seconds: float = 60.0
    max_messages: int = 1000
    max_replays: int = 10
    max_retries: int = 2


@dataclass
class DiscoveryReport:
    run_id: str
    status: DiscoveryState
    levels_attempted: list[str] = field(default_factory=list)
    levels_passed: list[str] = field(default_factory=list)
    highest_stable_level: str = "Level 0"
    failure_classification: FailureClassification | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


class SafeDiscoveryCampaign:
    """Orchestrates progressive test discovery with strict safety stops and checkpoints."""

    def __init__(self, limits: DiscoveryLimits | None = None, run_id: str = "run_discovery_001"):
        self.limits = limits or DiscoveryLimits()
        self.run_id = run_id
        self.state = DiscoveryState.INITIALIZED
        self.events: list[dict[str, Any]] = []

    def _log_event(self, event_type: str, **kwargs) -> None:
        evt = {"event": event_type, "run_id": self.run_id, "timestamp": time.time(), **kwargs}
        self.events.append(evt)
        log.info("discovery.%s %s", event_type, " ".join(f"{k}={v}" for k, v in kwargs.items()))

    def run_campaign(
        self,
        safety_precheck: Callable[[], bool],
        levels: list[tuple[str, Callable[[], Any]]],
    ) -> DiscoveryReport:
        """Execute levels progressively with checkpoint validation and fail-fast safety stops."""
        start_time = time.perf_counter()
        self._log_event("started", max_workers=self.limits.max_workers)

        # 1. Pre-discovery Safety Gate
        self.state = DiscoveryState.SAFETY_CHECKED
        try:
            passed_safety = safety_precheck()
            if not passed_safety:
                self.state = DiscoveryState.BLOCKED
                self._log_event("safety_failed")
                return DiscoveryReport(
                    run_id=self.run_id,
                    status=self.state,
                    failure_classification=FailureClassification.RELEASE_BLOCKER,
                    duration_seconds=time.perf_counter() - start_time,
                )
        except Exception as exc:
            self.state = DiscoveryState.BLOCKED
            self._log_event("safety_exception", error=str(exc))
            return DiscoveryReport(
                run_id=self.run_id,
                status=self.state,
                failure_classification=FailureClassification.RELEASE_BLOCKER,
                diagnostics={"error": str(exc)},
                duration_seconds=time.perf_counter() - start_time,
            )

        self._log_event("safety_passed")

        attempted: list[str] = []
        passed: list[str] = []
        highest_stable: str = "Level 0 (Safety Check)"

        # 2. Progressive Escalation
        for level_name, level_fn in levels:
            elapsed = time.perf_counter() - start_time
            if elapsed > self.limits.max_runtime_seconds:
                self.state = DiscoveryState.STOPPED_SAFELY
                self._log_event("limit_reached", reason="timeout", elapsed=elapsed)
                break

            self.state = DiscoveryState.DISCOVERING
            attempted.append(level_name)
            self._log_event("level_started", level=level_name)

            success = False
            error_diag: dict[str, Any] = {}
            for attempt in range(self.limits.max_retries + 1):
                try:
                    level_fn()
                    success = True
                    break
                except Exception as exc:
                    error_diag = {"error": str(exc), "attempt": attempt + 1}
                    self._log_event("retry", level=level_name, attempt=attempt + 1, error=str(exc))

            if success:
                self.state = DiscoveryState.CHECKPOINT
                passed.append(level_name)
                highest_stable = level_name
                self._log_event("checkpoint_passed", level=level_name)
            else:
                self.state = DiscoveryState.FAILED
                self._log_event("level_failed", level=level_name, **error_diag)
                return DiscoveryReport(
                    run_id=self.run_id,
                    status=self.state,
                    levels_attempted=attempted,
                    levels_passed=passed,
                    highest_stable_level=highest_stable,
                    failure_classification=FailureClassification.IMPLEMENTATION_DEFECT,
                    diagnostics=error_diag,
                    duration_seconds=time.perf_counter() - start_time,
                )

        if len(passed) == len(levels):
            self.state = DiscoveryState.COMPLETED
        elif self.state not in (DiscoveryState.FAILED, DiscoveryState.BLOCKED):
            self.state = DiscoveryState.STOPPED_SAFELY

        self._log_event("completed", state=self.state.value)

        return DiscoveryReport(
            run_id=self.run_id,
            status=self.state,
            levels_attempted=attempted,
            levels_passed=passed,
            highest_stable_level=highest_stable,
            duration_seconds=time.perf_counter() - start_time,
        )
