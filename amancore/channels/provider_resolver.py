"""Central provider resolution — THE single decision point for channel config.

Bridge migration (owner spec §6): every composition root
  C1  channels/webhook_server.build_runtime()
  C2  ops/scheduler_adapter.build_adapters()
  C3  ops/scheduler_adapter.build_probe_adapter()
must resolve channel configuration through THIS module so the live server,
the scheduler process and the health probes can never disagree
(`webhook=bridge, scheduler=graph` is a banned state).

mode ≠ transport (owner spec §8): `mode: bridge` selects the local-bridge
provider family; the actual transport (baileys / private / realtime) lives in
the `providers:` config block and is opaque to AmanCore.

Legacy semantics preserved byte-for-byte for mock/production modes:
  - whatsapp: production mode only under the audited production.yaml overlay
    (block_unless_production_enabled stays the second, send-time gate)
  - telegram: declared mode kept; the environment gate blocks sends
  - facebook/instagram: forced to mock unless the global overlay is on
"""

from __future__ import annotations

import os

BRIDGE_MODE = "bridge"
VALID_MODES = ("mock", "sandbox", "production", BRIDGE_MODE)
BRIDGE_DEFAULT_BASE_URL = "http://127.0.0.1:8765"
BRIDGE_TOKEN_ENV = "AMANCORE_BRIDGE_TOKEN"
BRIDGE_INGRESS_TOKEN_ENV = "BRIDGE_INGRESS_TOKEN"

_KNOWN_CHANNELS = ("whatsapp", "telegram", "facebook", "instagram")


def production_enabled(prod_env: dict | None) -> bool:
    """Audited owner gate from configs/production.yaml environment block."""
    env = prod_env or {}
    return bool(env.get("production_enabled")) and env.get("mode") == "production"


def bridge_enabled_for_any_channel(channels_cfg: dict | None) -> bool:
    """True when at least one channel declares mode: bridge (env validation)."""
    channels = channels_cfg or {}
    return any(
        dict(channels.get(ch) or {}).get("mode") == BRIDGE_MODE
        for ch in _KNOWN_CHANNELS
    )


def resolve_channel_config(channel: str, channels_cfg: dict | None,
                           prod_env: dict | None) -> dict | None:
    """Resolve one channel block into its EFFECTIVE config.

    Returns None when the channel is absent or disabled. Raises ValueError on
    an unknown mode (loud misconfiguration > silent fallback).
    """
    channels = channels_cfg or {}
    block = dict(channels.get(channel) or {})
    if not block:
        return None
    # whatsapp has no `enabled` key historically — always registered
    if not block.get("enabled", channel == "whatsapp"):
        return None

    cfg = dict(block)
    raw_mode = str(cfg.get("mode", "mock") or "mock")
    if raw_mode not in VALID_MODES:
        raise ValueError(f"invalid {channel} mode: {raw_mode}")
    # idempotent resolution: a config that already carries an environment
    # overlay is ALREADY RESOLVED (e.g. a probe re-resolving a runtime
    # config) — pass through unchanged so C1==C2==C3 parity is exact
    if isinstance(cfg.get("environment"), dict):
        return cfg
    glob_on = production_enabled(prod_env)

    if raw_mode == BRIDGE_MODE:
        return _resolve_bridge(channel, cfg, channels, glob_on, prod_env)

    if channel == "whatsapp":
        if glob_on:
            cfg["mode"] = "production"
            cfg["environment"] = {"production_enabled": True, "mode": "production"}
            # credentials/identity come from env (never hardcoded in yaml)
            cfg.setdefault("phone_number_id",
                           os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""))
            cfg.setdefault("api_version",
                           os.environ.get("WHATSAPP_API_VERSION", "v21.0"))
        else:
            # legacy scheduler affordance: AMANCORE_ENV names the mock env
            cfg.setdefault("mode", os.environ.get("AMANCORE_ENV", "mock"))
            cfg.setdefault("environment", {
                "production_enabled": False,
                "mode": (prod_env or {}).get("mode", "mock")})
        return cfg

    # telegram / facebook / instagram — same shape as the live composition root
    if glob_on and raw_mode == "production":
        cfg["mode"] = "production"
        cfg["environment"] = {"production_enabled": True, "mode": "production"}
    elif channel == "telegram":
        # keep the declared mode; the environment gate blocks external sends
        cfg.setdefault("environment", {
            "production_enabled": False,
            "mode": (prod_env or {}).get("mode", "mock")})
    else:
        cfg["mode"] = "mock"
        cfg["environment"] = {
            "production_enabled": False,
            "mode": (prod_env or {}).get("mode", "mock")}
    return cfg


def _resolve_bridge(channel: str, cfg: dict, channels: dict,
                    glob_on: bool, prod_env: dict | None) -> dict:
    """mode: bridge — local bridge provider family + transport block."""
    cfg["mode"] = BRIDGE_MODE
    # the SAME audited production gate applies to external bridge sends
    cfg["environment"] = {
        "production_enabled": glob_on,
        "mode": "production" if glob_on else "mock",
    }
    prov = dict((channels.get("providers") or {}).get(channel) or {})
    cfg["bridge"] = {
        "base_url": str(prov.get("base_url")
                        or os.environ.get("AMANCORE_BRIDGE_URL",
                                          BRIDGE_DEFAULT_BASE_URL)),
        "token_env": str(prov.get("token_env") or BRIDGE_TOKEN_ENV),
        "transport": str(prov.get("transport") or channel),
        "shadow": bool(prov.get("shadow") or cfg.get("shadow")),
        "browser_fallback": bool(prov.get("browser_fallback")),
        "connect_timeout": float(prov.get("connect_timeout", 3.0)),
        "read_timeout": float(prov.get("read_timeout", 30.0)),
        "connect_retries": int(prov.get("connect_retries", 2)),
    }
    # bridge ingress authenticates with X-Bridge-Token at /bridge/inbound —
    # the Meta HMAC webhook handshake is not part of this transport
    cfg["signature_required"] = False
    return cfg


def build_channel_adapter(channel: str, cfg: dict):
    """Construct the adapter for a RESOLVED config (resolver keeps this so
    all three roots share one construction path too)."""
    mode = (cfg or {}).get("mode", "mock")
    if mode == BRIDGE_MODE:
        if channel == "whatsapp":
            from .bridge_whatsapp import BridgeWhatsAppAdapter

            return BridgeWhatsAppAdapter(cfg)
        if channel in ("facebook", "instagram"):
            from .bridge_meta import build_meta_bridge_adapter

            return build_meta_bridge_adapter(channel, cfg)
        raise KeyError(f"no bridge adapter for channel '{channel}'")
    if channel == "whatsapp":
        from .whatsapp import WhatsAppAdapter

        return WhatsAppAdapter(cfg)
    if channel == "telegram":
        from .telegram import TelegramAdapter

        return TelegramAdapter(cfg)
    if channel == "facebook":
        from .meta_channels import FacebookAdapter

        return FacebookAdapter(cfg)
    if channel == "instagram":
        from .meta_channels import InstagramAdapter

        return InstagramAdapter(cfg)
    raise KeyError(f"no adapter registered for channel '{channel}'")
