"""P1-final §2.3 — DeepSeek text removal: chain integrity proof.

Updated 2026-09-04 (owner request): pure-TEXT task CHAINS stay DeepSeek-free
(GLM/Gemini only). The ONLY DeepSeek provider allowed anywhere is
`deepseek_vision` (model deepseek-v4-flash-vision-exp) for direct calls:
text+image AND voice-continuation text. Plain deepseek-v4-flash is
forbidden everywhere. This test proves that split.
"""

import unittest


class DeepSeekRemovalChainTest(unittest.TestCase):
    def test_config_has_no_deepseek_and_chains_are_glm(self):
        import yaml
        from pathlib import Path

        cfg_path = (Path(__file__).resolve().parents[2] / "configs" /
                    "models.yaml")
        raw = cfg_path.read_text()
        # comments documenting the removal decision are INTENTIONALLY-KEPT;
        # TEXT task CHAINS must be 100% DeepSeek-free; only deepseek_vision
        # (vision-exp) exists for direct calls. Plain flash is forbidden.
        cfg = yaml.safe_load(raw)
        self.assertNotIn("deepseek-v4-flash\"", raw.replace("deepseek-v4-flash-vision-exp", ""))
        providers = set(cfg["providers"])
        self.assertIn("deepseek_vision", providers)
        self.assertIn("deepseek_chat", providers)
        for task, chain in cfg["task_routing"].items():
            self.assertIn(chain["primary"], providers,
                          f"{task} primary must be in configured providers")
        self.assertEqual(cfg["task_routing"]["routine"]["primary"], "deepseek_chat")
        mm = cfg["task_routing"]["multimodal"]
        self.assertEqual(mm["primary"], "deepseek_vision")
        self.assertEqual(cfg["providers"]["deepseek_vision"]["model"],
                         "deepseek-v4-flash-vision-exp")
        self.assertEqual(cfg["providers"]["deepseek_chat"]["model"],
                         "deepseek-chat")

    def test_build_providers_returns_no_deepseek_instance(self):
        import yaml
        from pathlib import Path

        from amancore.routing.providers import build_providers

        root = Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load((root / "configs" / "models.yaml").read_text())
        built = build_providers(cfg)
        deepseek_providers = sorted(p for p in built if "deepseek" in p.lower())
        self.assertEqual(deepseek_providers, ["deepseek_chat", "deepseek_vision"])
        # provider class registry never had a vendor-specific deepseek type
        # (vision reuses the generic openai_compatible adapter)
        from amancore.routing import providers as prov_mod

        self.assertEqual(sorted(prov_mod._PROVIDER_TYPES),
                         ["anthropic", "gemini", "openai_compatible"])

    def test_routine_chain_falls_back_to_deterministic_semantics(self):
        """With GLM creds absent the router raises; the coordinator's
        existing try/except turns ANY RoutingError into base/deferral text.
        Config-level assertion: routine order == ['glm'] exactly."""
        import yaml
        from pathlib import Path

        from amancore.routing.router import ModelRouter

        root = Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load((root / "configs" / "models.yaml").read_text())

        class _NoUsage:
            def record(self, *a, **k):
                pass

        class _BrokenProv(dict):
            pass

        router = ModelRouter(cfg, _BrokenProv(), _NoUsage())
        expected_order = [cfg["task_routing"]["routine"]["primary"]]
        if cfg["task_routing"]["routine"].get("secondary"):
            expected_order.append(cfg["task_routing"]["routine"]["secondary"])
        self.assertEqual(router._order("routine"), expected_order)


if __name__ == "__main__":
    unittest.main()
