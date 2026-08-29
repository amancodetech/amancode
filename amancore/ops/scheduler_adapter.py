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


def build_adapters() -> dict:
    """Build the channel adapter registry from configs + environment.

    Bridge migration (owner spec §6): resolution is delegated to the central
    provider resolver — the scheduler can never disagree with the webhook
    runtime about which provider backs a channel."""
    from ..channels.provider_resolver import (
        build_channel_adapter,
        resolve_channel_config,
    )

    channels_cfg = channels_overlay()
    prod_env = production_overlay()
    adapters: dict = {}
    for channel in ("whatsapp", "telegram", "facebook", "instagram"):
        cfg = resolve_channel_config(channel, channels_cfg, prod_env)
        if cfg is None:
            continue
        adapters[channel] = build_channel_adapter(channel, cfg)
    return adapters


def build_probe_adapter(channel: str, channel_cfg: dict):
    """Health-check probe.

    Bridge migration: the probe resolves through the SAME resolver as the
    runtime (C1==C2==C3 parity, owner spec §38). The raw channel block is
    passed unmodified — `mock stays mock` remains true because the resolver
    only elevates to production under the audited production.yaml overlay,
    which a raw test/tool block never carries."""
    from ..channels.provider_resolver import (
        build_channel_adapter,
        resolve_channel_config,
    )

    if channel not in ("whatsapp", "telegram", "facebook", "instagram"):
        raise KeyError(f"no probe adapter registered for channel '{channel}'")
    cfg = resolve_channel_config(channel, {channel: channel_cfg}, {})
    if cfg is None:
        raise KeyError(f"no probe adapter registered for channel '{channel}'")
    return build_channel_adapter(channel, cfg)
