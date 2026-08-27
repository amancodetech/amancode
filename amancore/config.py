"""Configuration + environment loading (secrets stay out of code).

Secrets are read from environment variables only. A local `.env` is parsed
for convenience (values are NOT overridden if already present in the process
environment).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


def load_env(path: Path, mutate_environ: bool = True) -> dict[str, str]:
    """Parse a `.env` file into KEY=VALUE pairs (no interpolation)."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # never override an already-set process env var
        if mutate_environ:
            os.environ.setdefault(key, value)
        values[key] = value
    return values


def _load_yaml(path: Path, optional: bool = False) -> dict[str, Any]:
    if not path.exists():
        if optional:
            return {}
        raise ConfigError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"config file must be a mapping: {path}")
    return data


@dataclass
class Config:
    """Loaded AmanCore configuration."""

    root: Path
    app: dict[str, Any] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    pricing: dict[str, Any] = field(default_factory=dict)
    lead_scoring: dict[str, Any] = field(default_factory=dict)
    retention: dict[str, Any] = field(default_factory=dict)
    channels: dict[str, Any] = field(default_factory=dict)
    support: dict[str, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    production: dict[str, Any] = field(default_factory=dict)
    insights: dict[str, Any] = field(default_factory=dict)
    scheduler: dict[str, Any] = field(default_factory=dict)

    @property
    def database_path(self) -> Path:
        # INCIDENT FIX 2026-08-24: env override must win — a silent ignore here
        # routed load-test writes into the PRODUCTION database (WABA ban).
        import os as _os

        env_db = _os.environ.get("DATABASE_PATH", "").strip()
        if env_db:
            return Path(env_db)
        raw = self.app.get("database_path", "storage/aman_core.db")
        p = Path(raw)
        return p if p.is_absolute() else self.root / p

    @property
    def shadow_rate(self) -> float:
        return float(self.pricing.get("shadow_rate", self.app.get("shadow_rate", 40)))


def load_config(root: Path, mutate_environ: bool = True) -> Config:
    """Load all configs + local .env, returning a Config object.

    mutate_environ=False keeps secrets OUT of os.environ — tests and any
    non-CLI caller MUST use it (REAUD MEDIUM: env pollution was the class
    of defect behind the 2026-08-24 WABA incident)."""
    load_env(root / ".env", mutate_environ=mutate_environ)
    cfg = Config(
        root=root,
        app=_load_yaml(root / "configs" / "app.yaml"),
        models=_load_yaml(root / "configs" / "models.yaml"),
        # pricing.yaml was removed from the source tree (Brain is the single
        # source of truth); keep an empty shim so legacy readers stay inert.
        pricing={},
        lead_scoring=_load_yaml(root / "configs" / "lead_scoring.yaml"),
        retention=_load_yaml(root / "configs" / "retention.yaml"),
        channels=_load_yaml(root / "configs" / "channels.yaml"),
        support=_load_yaml(root / "configs" / "support.yaml"),
        analytics=_load_yaml(root / "configs" / "analytics.yaml"),
        alerts=_load_yaml(root / "configs" / "alerts.yaml"),
        production=_load_yaml(root / "configs" / "production.yaml"),
        insights=_load_yaml(root / "configs" / "insights.yaml"),
        scheduler=_load_yaml(root / "configs" / "scheduler.yaml"),
    )
    return cfg

# ── SRV-401/S3: fail-fast on missing secrets for ENABLED integrations ────────
# A deleted env var used to boot green and fail every send silently.
REQUIRED_ENV_BY_FEATURE = {
    "production_whatsapp": [
        "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN",
    ],
    "owner_alerts_telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
}


def _feature_active(feature: str, cfg: "Config", environ) -> bool:
    if feature == "production_whatsapp":
        try:
            return bool(cfg.production.get("environment", {}).get("production_enabled", False))
        except Exception:  # noqa: BLE001
            return False
    if feature == "owner_alerts_telegram":
        return environ.get("OWNER_ALERT_CHANNEL", "").strip().lower() == "telegram"
    return False


def validate_required_env(cfg: "Config", environ=None) -> list[str]:
    """Return human-readable list of missing REQUIRED secrets (empty = OK)."""
    import os as _os

    environ = environ if environ is not None else _os.environ
    missing = []
    for feature, keys in REQUIRED_ENV_BY_FEATURE.items():
        if not _feature_active(feature, cfg, environ):
            continue
        for key in keys:
            if not str(environ.get(key, "")).strip():
                missing.append(f"{key} (required by {feature})")
    return missing
