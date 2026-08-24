"""Unified logging with correlation id + secret redaction."""

from __future__ import annotations

import contextvars
import logging
import re

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# secret-bearing keys followed by a value: `token=abc`, `Authorization: Bearer x`
_SECRET_PAIR = re.compile(
    r"((?:api[_-]?key|access[_-]?token|token|secret|password|authorization|auth)"
    r"[a-z0-9_]*)\s*[=:]\s*([\"']?[^\s,\"']+[\"']?)",
    re.IGNORECASE,
)
# standalone `Bearer <jwt-like value>`
_SECRET_BEARER = re.compile(
    r"\b(bearer)\s+([A-Za-z0-9._\-]{8,})\b", re.IGNORECASE
)
_REDACTED = "<redacted>"


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — never break logging on bad args
            return True
        msg = _SECRET_BEARER.sub(lambda m: f"{m.group(1)} {_REDACTED}", msg)
        msg = _SECRET_PAIR.sub(lambda m: f"{m.group(1)}={_REDACTED}", msg)
        # freeze the final message; drop args so % formatting can't re-inject secrets
        record.msg = msg
        record.args = None
        return True


_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(correlation)s%(message)s"


class _CorrelationFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        cid = _correlation_id.get()
        record.correlation = f"cid={cid} " if cid else ""
        return super().format(record)


def set_correlation_id(cid: str | None) -> None:
    _correlation_id.set(cid)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger("amancore")
    if any(isinstance(h, StreamHandlerCompat) for h in root.handlers):
        root.setLevel(level.upper())
        return
    handler = StreamHandlerCompat()
    handler.setFormatter(_CorrelationFormatter(_FORMAT))
    handler.addFilter(SecretRedactionFilter())
    root.setLevel(level.upper())
    root.addHandler(handler)
    root.propagate = False


class StreamHandlerCompat(logging.StreamHandler):
    """Named marker so setup_logging is idempotent across repeated calls."""


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"amancore.{name}")
