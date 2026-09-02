"""Test Fixtures and Isolation Package."""

from .isolation import (
    assert_not_production_environment,
    assert_not_production_database,
    assert_no_live_credentials,
    NetworkGuard,
)
from .db import (
    assert_test_database,
    isolated_db,
    transactional_db,
    wipe_db,
)
from .ids import ids, DeterministicIDGenerator
from .clock import clock, DeterministicClock
from .llm import DeterministicLLMFake
from .providers import FakeMessagingProvider, FakePaymentProvider
from .failures import failure_injector, FailureInjector
from .replay import replay_message, assert_replay_idempotent
from .concurrency import run_concurrently
from .env import isolated_env, isolated_temp_dir
from .tenant_isolation import (
    isolated_projects,
    assert_project_isolated,
    assert_no_cross_project_requirements,
    assert_no_cross_project_decisions,
    assert_no_cross_project_questions,
    assert_no_cross_project_conflicts,
    assert_no_cross_project_scopes,
)
from .discovery import (
    DiscoveryState,
    FailureClassification,
    DiscoveryLimits,
    DiscoveryReport,
    SafeDiscoveryCampaign,
)
from .multiprocess import (
    run_in_processes,
    capture_sqlite_lock_diagnostics,
)

__all__ = [
    "assert_not_production_environment",
    "assert_not_production_database",
    "assert_no_live_credentials",
    "NetworkGuard",
    "assert_test_database",
    "isolated_db",
    "transactional_db",
    "wipe_db",
    "ids",
    "DeterministicIDGenerator",
    "clock",
    "DeterministicClock",
    "DeterministicLLMFake",
    "FakeMessagingProvider",
    "FakePaymentProvider",
    "failure_injector",
    "FailureInjector",
    "replay_message",
    "assert_replay_idempotent",
    "run_concurrently",
    "isolated_env",
    "isolated_temp_dir",
    "isolated_projects",
    "assert_project_isolated",
    "assert_no_cross_project_requirements",
    "assert_no_cross_project_decisions",
    "assert_no_cross_project_questions",
    "assert_no_cross_project_conflicts",
    "assert_no_cross_project_scopes",
    "DiscoveryState",
    "FailureClassification",
    "DiscoveryLimits",
    "DiscoveryReport",
    "SafeDiscoveryCampaign",
    "run_in_processes",
    "capture_sqlite_lock_diagnostics",
]
