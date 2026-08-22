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


def load_env(path: Path) -> dict[str, str]:
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
        os.environ.setdefault(key, value)
        values[key] = value
    return values


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
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

    @property
    def database_path(self) -> Path:
        raw = self.app.get("database_path", "storage/aman_core.db")
        p = Path(raw)
        return p if p.is_absolute() else self.root / p

    @property
    def shadow_rate(self) -> float:
        return float(self.pricing.get("shadow_rate", self.app.get("shadow_rate", 40)))


def load_config(root: Path) -> Config:
    """Load all configs + local .env, returning a Config object."""
    load_env(root / ".env")
    cfg = Config(
        root=root,
        app=_load_yaml(root / "configs" / "app.yaml"),
        models=_load_yaml(root / "configs" / "models.yaml"),
        pricing=_load_yaml(root / "configs" / "pricing.yaml"),
        lead_scoring=_load_yaml(root / "configs" / "lead_scoring.yaml"),
        retention=_load_yaml(root / "configs" / "retention.yaml"),
    )
    return cfg
