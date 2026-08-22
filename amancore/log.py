"""Unified logging with correlation id + secret redaction."""

from __future__ import annotations

import contextvars
import logging
import re

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# never log these values
_SECRET_KEYS = re.compile(
    r"(api[_-]?key|token|secret|password|authorization|bearer)",
    re.IGNORECASE,
)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # replace `key=value` / `key: value` where key looks secret
        record.msg = _SECRET_KEYS.sub(lambda m: m.group(0), msg)
        if record.args:
            record.args = tuple(
                _SECRET_KEYS.sub("<redacted>", str(a)) for a in record.args
            )
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
    handler = logging.StreamHandler()
    handler.setFormatter(_CorrelationFormatter(_FORMAT))
    handler.addFilter(SecretRedactionFilter())
    root = logging.getLogger("amancore")
    root.setLevel(level.upper())
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"amancore.{name}")
