"""Owner Alert Service — config-driven real transport (Phase 3H).

Legacy sink bridge: send_owner_alert() now routes through the AlertDispatcher
(telegram/email when available, log fallback). NEVER sends to an unconfigured
destination; transport_status() reports NOT_CONFIGURED otherwise.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger("owner_alert")


def _dispatcher():
    from ..config import load_config
    from ..ops.alerts import AlertDispatcher, resolve_transport
    from ..storage.db import open_database
    from ..util import get_project_root

    root = get_project_root()
    cfg = load_config(root)
    db = open_database(cfg.database_path, root / "amancore" / "storage" / "schema.sql")
    dispatcher = AlertDispatcher(db, config=cfg.scheduler.get("alert", {}),
                                 transport=resolve_transport(cfg.scheduler.get("alert", {})))
    return dispatcher, db


def send_owner_alert(level: str, message: str, correlation_id: str | None = None) -> None:
    """Dispatch an owner alert via the configured transport (log fallback)."""
    try:
        dispatcher, db = _dispatcher()
        try:
            dispatcher.dispatch(
                severity=level.upper() if level.upper() in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "HIGH",
                category="owner",
                title="Owner alert",
                summary=message,
                action_required="review",
                correlation_id=correlation_id,
            )
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — alert must never crash the system
        log.warning("[OWNER ALERT][%s] %s (transport error: %s)", level.upper(), message, exc)


def transport_status() -> str:
    from ..config import load_config
    from ..ops.alerts import transport_status as _ts
    from ..util import get_project_root

    cfg = load_config(get_project_root())
    return _ts(cfg.scheduler.get("alert", {}))
