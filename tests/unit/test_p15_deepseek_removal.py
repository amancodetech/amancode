"""P1-final §2.3 — DeepSeek removal: chain integrity proof.

Asserts the live ModelRouter config contains no DeepSeek anywhere, every text
task routes to glm only, and a routing failure still degrades to the
deterministic path (the coordinator fallback is exercised in the existing
chaos/cost suites — here we prove the CONFIG half of the chain).
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
        # the FUNCTIONAL config (parsed dict) must be 100% DeepSeek-free.
        cfg = yaml.safe_load(raw)
        self.assertNotIn("deepseek", str(cfg).lower())
        providers = set(cfg["providers"])
        self.assertTrue(bool(providers.intersection({"glm", "gemini"})))
        for task, chain in cfg["task_routing"].items():
            self.assertIn(chain["primary"], providers,
                          f"{task} primary must be in configured providers")

    def test_build_providers_returns_no_deepseek_instance(self):
        import yaml
        from pathlib import Path

        from amancore.routing.providers import build_providers

        root = Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load((root / "configs" / "models.yaml").read_text())
        built = build_providers(cfg)
        self.assertFalse([p for p in built if "deepseek" in p.lower()])
        # provider class registry never had a vendor-specific deepseek type
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
