"""Shared channel adapter composition for out-of-runtime processes.

The scheduler (separate process) must build the SAME adapter registry as the
webhook runtime — one truth source (configs/production.yaml), one factory.
Provider-specific construction is confined to THIS module and
webhook_server.build_runtime (composition roots).

FIX (channel-neutralization audit): the old registry._drain minted an adapter
with mode=AMANCORE_ENV and NO environment overlay, so in production every
scheduler-driven send raised ProductionNotEnabledError and died on retry.
Reading production.yaml here restores policy parity with build_runtime while
keeping the gate itself (block_unless_production_enabled) fully in force.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def production_overlay() -> dict:
    """Read the authoritative enablement state from configs/production.yaml."""
    root = Path(__file__).resolve().parents[2]
    prod_file = root / "configs" / "production.yaml"
    try:
        prod = yaml.safe_load(prod_file.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — unreadable config means "not enabled"
        return {}
    return dict(prod.get("environment") or {})


def channels_overlay() -> dict:
    """Read configs/channels.yaml (per-channel blocks)."""
    root = Path(__file__).resolve().parents[2]
    try:
        return yaml.safe_load((root / "configs" / "channels.yaml")
                              .read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — unreadable config means "no channels"
        return {}


def _telegram_cfg(tg_block: dict, enabled: bool) -> dict:
    cfg = dict(tg_block or {})
    cfg["mode"] = "production" if (enabled and tg_block.get("mode") == "production") \
        else "mock"
    cfg["environment"] = {
        "production_enabled": bool(enabled and tg_block.get("mode") == "production"),
        "mode": cfg["mode"],
    }
    return cfg


def build_adapters() -> dict:
    """Build the channel adapter registry from configs + environment."""
    from ..channels.whatsapp import WhatsAppAdapter

    env_overlay = production_overlay()
    enabled = bool(env_overlay.get("production_enabled")) \
        and env_overlay.get("mode") == "production"

    wa_cfg: dict = {
        # mock stays the default outside explicit enablement
        "mode": "production" if enabled else os.environ.get("AMANCORE_ENV", "mock"),
        "phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        "access_token_env": "WHATSAPP_ACCESS_TOKEN",
        "verify_token_env": "WHATSAPP_VERIFY_TOKEN",
        "app_secret_env": "WHATSAPP_APP_SECRET",
        "signature_required": os.environ.get("WHATSAPP_SIGNATURE_REQUIRED", "true") != "false",
        "base_url": env_overlay.get("base_url", "https://graph.facebook.com"),
        "api_version": env_overlay.get("api_version", "v24.0"),
        "environment": {
            "production_enabled": enabled,
            "mode": "production" if enabled else "mock",
        },
    }
    adapters: dict = {"whatsapp": WhatsAppAdapter(wa_cfg)}

    # Telegram CUSTOMER channel — only when explicitly configured in
    # channels.yaml; sends stay policy-DENIED until enabled+customer_messaging.
    tg_block = channels_overlay().get("telegram") or {}
    if tg_block.get("enabled"):
        from ..channels.telegram import TelegramAdapter

        adapters["telegram"] = TelegramAdapter(_telegram_cfg(tg_block, enabled))
    return adapters


def build_probe_adapter(channel: str, channel_cfg: dict):
    """Health-check probe: adapter built from the CHANNEL's own config block
    (mock stays mock) — never the global production overlay."""
    if channel == "whatsapp":
        from ..channels.whatsapp import WhatsAppAdapter

        return WhatsAppAdapter(dict(channel_cfg or {}))
    if channel == "telegram":
        from ..channels.telegram import TelegramAdapter

        return TelegramAdapter(dict(channel_cfg or {}))
    raise KeyError(f"no probe adapter registered for channel '{channel}'")
