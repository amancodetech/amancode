"""Test Environment Safety, Guard Assertions, and Isolation Infrastructure."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

# Disallowed production database file names
PRODUCTION_DB_NAMES = {"aman_core.db", "production.db", "amancode.db"}

# Known test indicators
TEST_ENVIRONMENT_VARS = {"AMANCODE_ISOLATED", "LOAD_MOCK_LLM", "TESTING"}


def assert_not_production_environment() -> None:
    """Verify that current process is explicitly configured as a test environment."""
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env in {"production", "prod"}:
        raise RuntimeError("SAFETY VIOLATION: Tests cannot run in PRODUCTION environment!")


def assert_not_production_database(db_path: Path | str) -> None:
    """Verify that a database path is strictly a temporary or designated test database."""
    resolved = Path(db_path).resolve()
    if resolved.name in PRODUCTION_DB_NAMES:
        raise RuntimeError(
            f"SAFETY VIOLATION: Refusing to open production database '{resolved.name}' during test execution!"
        )


def assert_no_live_credentials() -> None:
    """Ensure tests are not accidentally utilizing live production secret keys."""
    # When running in isolated test mode, live keys must either be dummy values or mocked
    if os.environ.get("STRICT_TEST_ISOLATION"):
        for key in ("LIVE_STRIPE_KEY", "LIVE_WHATSAPP_TOKEN", "LIVE_META_APP_SECRET"):
            if os.environ.get(key):
                raise RuntimeError(f"SAFETY VIOLATION: Live credential '{key}' detected in isolated test environment!")


class NetworkGuard:
    """Context manager and helper that forbids any external network socket connections during tests."""

    def __init__(self, allowed_hosts: set[str] | None = None):
        self.allowed_hosts = allowed_hosts or {"127.0.0.1", "localhost"}
        self._orig_connect = socket.socket.connect
        self._orig_create_connection = socket.create_connection

    def __enter__(self):
        def guarded_connect(sock_self, address):
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
            if host not in self.allowed_hosts:
                raise RuntimeError(f"NETWORK BLOCKED: Attempted external network call to {host} in test!")
            return self._orig_connect(sock_self, address)

        def guarded_create_connection(address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
            if host not in self.allowed_hosts:
                raise RuntimeError(f"NETWORK BLOCKED: Attempted external network connection to {host} in test!")
            return self._orig_create_connection(address, *args, **kwargs)

        socket.socket.connect = guarded_connect  # type: ignore[assignment]
        socket.create_connection = guarded_create_connection  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        socket.socket.connect = self._orig_connect  # type: ignore[assignment]
        socket.create_connection = self._orig_create_connection  # type: ignore[assignment]
