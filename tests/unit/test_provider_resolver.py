"""Provider resolver contract tests — one decision point for C1/C2/C3
(owner spec §6/§38) + bridge mode plumbing (§7/§8) + shadow (§31)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from amancore.channels.provider_resolver import (
    build_channel_adapter,
    bridge_enabled_for_any_channel,
    resolve_channel_config,
)
from amancore.ops.scheduler_adapter import build_adapters, build_probe_adapter

PROD_ON = {"production_enabled": True, "mode": "production"}
PROD_OFF = {"production_enabled": False, "mode": "mock"}


class ResolverSemanticsTests(unittest.TestCase):
    def test_absent_or_disabled_channel_is_none(self):
        self.assertIsNone(resolve_channel_config("whatsapp", {}, PROD_OFF))
        self.assertIsNone(resolve_channel_config(
            "telegram", {"telegram": {"enabled": False, "mode": "production"}},
            PROD_OFF))

    def test_invalid_mode_raises_loudly(self):
        with self.assertRaises(ValueError):
            resolve_channel_config(
                "whatsapp", {"whatsapp": {"mode": "carrier-pigeon"}}, PROD_OFF)

    def test_whatsapp_production_overlay(self):
        cfg = resolve_channel_config(
            "whatsapp", {"whatsapp": {"mode": "mock", "api_version": "v24.0"}},
            PROD_ON)
        self.assertEqual(cfg["mode"], "production")
        self.assertTrue(cfg["environment"]["production_enabled"])
        self.assertEqual(cfg["api_version"], "v24.0")  # block value wins

    def test_whatsapp_stays_mock_without_overlay(self):
        cfg = resolve_channel_config(
            "whatsapp", {"whatsapp": {"mode": "mock"}}, PROD_OFF)
        self.assertEqual(cfg["mode"], "mock")
        self.assertFalse(cfg["environment"]["production_enabled"])

    def test_meta_channels_forced_mock_without_overlay(self):
        block = {"facebook": {"enabled": True, "mode": "production"}}
        cfg = resolve_channel_config("facebook", block, PROD_OFF)
        self.assertEqual(cfg["mode"], "mock")
        self.assertFalse(cfg["environment"]["production_enabled"])

    def test_bridge_mode_resolves_transport_block(self):
        channels = {
            "whatsapp": {"mode": "bridge", "shadow": False},
            "providers": {"whatsapp": {"transport": "baileys",
                                       "base_url": "http://127.0.0.1:9999",
                                       "token_env": "MY_TOKEN",
                                       "shadow": True}},
        }
        cfg = resolve_channel_config("whatsapp", channels, PROD_ON)
        self.assertEqual(cfg["mode"], "bridge")
        self.assertEqual(cfg["bridge"]["transport"], "baileys")
        self.assertEqual(cfg["bridge"]["base_url"], "http://127.0.0.1:9999")
        self.assertEqual(cfg["bridge"]["token_env"], "MY_TOKEN")
        self.assertTrue(cfg["bridge"]["shadow"])
        # the SAME audited production gate governs bridge external sends
        self.assertTrue(cfg["environment"]["production_enabled"])
        # Meta HMAC webhook auth is not part of the bridge transport
        self.assertFalse(cfg["signature_required"])

    def test_bridge_mode_defaults_when_no_providers_block(self):
        cfg = resolve_channel_config(
            "instagram",
            {"instagram": {"enabled": True, "mode": "bridge"}}, PROD_OFF)
        self.assertEqual(cfg["mode"], "bridge")
        self.assertEqual(cfg["bridge"]["transport"], "instagram")
        self.assertEqual(cfg["bridge"]["base_url"], "http://127.0.0.1:8765")
        self.assertFalse(cfg["environment"]["production_enabled"])

    def test_bridge_enabled_for_any_channel_helper(self):
        self.assertTrue(bridge_enabled_for_any_channel(
            {"facebook": {"enabled": True, "mode": "bridge"}}))
        self.assertFalse(bridge_enabled_for_any_channel(
            {"facebook": {"enabled": True, "mode": "production"}}))


class CompositionRootParityTests(unittest.TestCase):
    """C1==C2==C3 — one resolver, one construction path (owner spec §38)."""

    BRIDGE_CHANNELS = {
        "whatsapp": {"mode": "bridge"},
        "telegram": {"enabled": True, "mode": "production"},
        "facebook": {"enabled": True, "mode": "bridge"},
        "instagram": {"enabled": True, "mode": "bridge"},
        "providers": {
            "whatsapp": {"transport": "baileys"},
            "facebook": {"transport": "private"},
            "instagram": {"transport": "realtime"},
        },
    }

    def _fingerprint(self, adapter) -> tuple:
        cfg = adapter.config
        bridge = cfg.get("bridge") or {}
        return (type(adapter).__name__, cfg.get("mode"),
                cfg.get("environment"), bridge.get("transport"),
                bridge.get("base_url"), bridge.get("shadow"))

    def test_c2_c3_same_provider_same_config(self):
        # C2: full registry build; C3: per-channel probe build — identical
        c2 = build_adapters()  # real configs (no bridge live) → smoke parity
        for ch in ("whatsapp", "telegram", "facebook", "instagram"):
            probe = build_probe_adapter(ch, c2[ch].config)
            self.assertEqual(type(probe), type(c2[ch]), ch)
            self.assertEqual(probe.config.get("mode"),
                             c2[ch].config.get("mode"), ch)

    def test_c2_registry_bridge_shapes_match_resolver(self):
        import copy

        from amancore.ops import scheduler_adapter as sa

        original_co = sa.channels_overlay
        original_po = sa.production_overlay
        sa.channels_overlay = lambda: copy.deepcopy(self.BRIDGE_CHANNELS)
        sa.production_overlay = lambda: dict(PROD_ON)
        try:
            registry = build_adapters()
        finally:
            sa.channels_overlay = original_co
            sa.production_overlay = original_po
        self.assertIn("whatsapp", registry)
        wa = registry["whatsapp"]
        self.assertEqual(type(wa).__name__, "BridgeWhatsAppAdapter")
        self.assertEqual(self._fingerprint(wa),
                         self._fingerprint(build_channel_adapter(
                             "whatsapp",
                             resolve_channel_config(
                                 "whatsapp", self.BRIDGE_CHANNELS, PROD_ON))))
        self.assertEqual(type(registry["facebook"]).__name__,
                         "BridgeFacebookAdapter")
        self.assertEqual(type(registry["instagram"]).__name__,
                         "BridgeInstagramAdapter")
        self.assertEqual(type(registry["telegram"]).__name__,
                         "TelegramAdapter")

    def test_build_runtime_uses_the_same_resolver_for_bridge(self):
        """C1 end-to-end: build_runtime against a bridge-mode config must
        produce bridge adapters (C1 == C2 == C3 parity at the live root)."""
        from amancore.channels.webhook_server import build_runtime

        tmp = tempfile.mkdtemp(prefix="amancore-c1-parity-")
        try:
            root = Path(tmp)
            (root / "configs").mkdir()
            shutil.copy("configs/app.yaml", root / "configs" / "app.yaml")
            shutil.copy("configs/models.yaml", root / "configs" / "models.yaml")
            shutil.copy("configs/production.yaml",
                        root / "configs" / "production.yaml")
            shutil.copy("configs/scheduler.yaml",
                        root / "configs" / "scheduler.yaml")
            for name in ("alerts", "analytics", "insights", "lead_scoring",
                         "retention", "support"):
                src = Path("configs") / f"{name}.yaml"
                if src.exists():
                    shutil.copy(src, root / "configs" / src.name)
            (root / "configs" / "channels.yaml").write_text(
                "whatsapp:\n  mode: bridge\n"
                "providers:\n  whatsapp:\n    transport: baileys\n"
                "    base_url: http://127.0.0.1:8765\n",
                encoding="utf-8")
            (root / "amancore").mkdir()
            shutil.copytree("amancore/storage", root / "amancore" / "storage")
            shutil.copytree("amancore/business_brain",
                            root / "amancore" / "business_brain")
            (root / ".env").write_text("", encoding="utf-8")
            import os as _os
            old = _os.environ.pop("DATABASE_PATH", None)
            try:
                runtime = build_runtime(root)
                wa = runtime["coordinator"].adapters.get("whatsapp")
                self.assertIsNotNone(wa)
                self.assertEqual(type(wa).__name__, "BridgeWhatsAppAdapter")
                self.assertEqual(wa.config["bridge"]["transport"], "baileys")
            finally:
                if old is not None:
                    _os.environ["DATABASE_PATH"] = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
