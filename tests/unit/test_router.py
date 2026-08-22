import unittest

from amancore.errors import RoutingError
from amancore.routing.models import ProviderResult
from amancore.routing.router import ModelRouter, UsageTracker


class FakeProvider:
    def __init__(self, pid, model, fail=False, text="hi"):
        self.provider_id = pid
        self.model = model
        self.fail = fail
        self.text = text

    def complete(self, messages, **kwargs):
        if self.fail:
            raise RoutingError("boom")
        return ProviderResult(text=self.text, input_tokens=10, output_tokens=5, model=self.model)


class RouterTest(unittest.TestCase):
    def _config(self):
        return {
            "task_routing": {
                "strategy": {"primary": "p1", "secondary": "p2", "fallback": None},
            },
            "pricing_per_million": {
                "p1": {"input": 1.0, "output": 2.0},
                "p2": {"input": 1.0, "output": 2.0},
            },
        }

    def test_classify(self):
        r = ModelRouter(self._config(), {})
        self.assertEqual(r.classify("strategy")["primary"], "p1")

    def test_classify_unknown(self):
        r = ModelRouter(self._config(), {})
        with self.assertRaises(RoutingError):
            r.classify("nope")

    def test_primary_success(self):
        providers = {"p1": FakeProvider("p1", "m1"), "p2": FakeProvider("p2", "m2")}
        r = ModelRouter(self._config(), providers)
        res = r.route("strategy", [{"role": "user", "content": "hi"}])
        self.assertEqual(res.provider, "p1")
        self.assertEqual(res.status, "ok")
        self.assertEqual(len(r.usage.records), 1)

    def test_fallback_on_primary_failure(self):
        providers = {"p1": FakeProvider("p1", "m1", fail=True), "p2": FakeProvider("p2", "m2")}
        r = ModelRouter(self._config(), providers)
        res = r.route("strategy", [{"role": "user", "content": "hi"}])
        self.assertEqual(res.provider, "p2")
        self.assertEqual(res.attempts, 2)

    def test_all_fail_raises(self):
        providers = {"p1": FakeProvider("p1", "m1", fail=True)}
        r = ModelRouter(self._config(), providers)
        with self.assertRaises(RoutingError):
            r.route("strategy", [{"role": "user", "content": "hi"}])
        # usage recorded an error for the failed attempt
        self.assertEqual(r.usage.records[-1]["status"], "error")


if __name__ == "__main__":
    unittest.main()
