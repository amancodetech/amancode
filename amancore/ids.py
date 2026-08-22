"""Deterministic identifier + timestamp helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """Return a URL-safe unique id (32 hex chars)."""
    return uuid.uuid4().hex


def utcnow() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
