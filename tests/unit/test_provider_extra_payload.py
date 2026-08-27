import unittest
from unittest import mock

from amancore.routing.providers import OpenAICompatibleProvider


class ExtraPayloadTest(unittest.TestCase):
    def test_extra_payload_merged_and_core_fields_protected(self):
        p = OpenAICompatibleProvider("glm", {
            "model": "glm-5.3-flash",
            "base_url_env": "X_BASE",
            "api_key_env": "X_KEY",
            "extra_payload": {"thinking": {"level": "low"}, "model": "HACK"},
        })
        captured = {}

        class R:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        with mock.patch.dict("os.environ", {"X_BASE": "http://x/v4", "X_KEY": "k"}), \
             mock.patch("amancore.routing.providers.requests.post",
                        side_effect=lambda url, json, headers, timeout: captured.update(payload=json) or R()):
            p.complete([{"role": "user", "content": "hi"}])

        self.assertEqual(captured["payload"]["thinking"], {"level": "low"})
        self.assertEqual(captured["payload"]["model"], "glm-5.3-flash")


if __name__ == "__main__":
    unittest.main()
