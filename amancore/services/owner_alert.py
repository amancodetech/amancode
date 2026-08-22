"""Owner Alert Service — abstraction.

Phase 3A: logs to the local sink only (no WhatsApp/Telegram yet).
The channel/destination are configuration values, never hardcoded.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger("owner_alert")


def send_owner_alert(level: str, message: str, correlation_id: str | None = None) -> None:
    """Dispatch an owner alert via the configured sink (log sink in Phase 3A)."""
    log.warning("[OWNER ALERT][%s] %s", level.upper(), message)
