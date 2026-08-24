"""SRV-401: auth hardening — S2 proxy-IP spoofing + limiter growth +
LAN cookie, S3 fail-fast secrets, S4 authenticated logout + CSP + body caps."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.channels.inbox import (  # noqa: E402
    InboxConfig, LoginRateLimiter, security_headers,
)
from amancore.config import Config, validate_required_env  # noqa: E402


class S2ProxyTrust(unittest.TestCase):
    def test_spoofed_cf_header_ignored_by_default(self):
        from amancore.channels.webhook_server import resolve_client_key

        headers = {"CF-Connecting-IP": "1.2.3.4"}
        self.assertEqual(resolve_client_key(headers, "203.0.113.9", False),
                         "203.0.113.9",
                         "spoofable header must NOT become the rate-limit key")

    def test_proxy_header_trusted_when_flagged(self):
        from amancore.channels.webhook_server import resolve_client_key

        headers = {"CF-Connecting-IP": "1.2.3.4"}
        self.assertEqual(resolve_client_key(headers, "203.0.113.9", True), "1.2.3.4")

    def test_missing_peer_falls_back_to_placeholder(self):
        from amancore.channels.webhook_server import resolve_client_key

        self.assertEqual(resolve_client_key({}, None, False), "?")


class S2CookieSecureFlag(unittest.TestCase):
    def test_defaults_off_for_lan_http(self):
        cfg = InboxConfig({})
        self.assertFalse(cfg.secure_cookie)

    def test_opt_in_via_env(self):
        cfg = InboxConfig({"INBOX_SECURE_COOKIE": "true"})
        self.assertTrue(cfg.secure_cookie)


class S3RequiredSecrets(unittest.TestCase):
    def _cfg(self, prod_enabled):
        production = {"environment": {"production_enabled": prod_enabled}}
        return Config(root=ROOT, app={}, models={}, pricing={}, lead_scoring={},
                      retention={}, channels={}, support={}, analytics={},
                      alerts={}, production=production, insights={}, scheduler={})

    def test_production_without_whatsapp_secrets_listed(self):
        missing = validate_required_env(self._cfg(True), environ={})
        joined = "\n".join(missing)
        for key in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET"):
            self.assertIn(key, joined)

    def test_shadow_mode_no_requirements(self):
        self.assertEqual(validate_required_env(self._cfg(False), environ={}), [])

    def test_telegram_alerts_required_when_selected(self):
        missing = validate_required_env(
            self._cfg(False),
            environ={"OWNER_ALERT_CHANNEL": "telegram"})
        self.assertIn("TELEGRAM_BOT_TOKEN (required by owner_alerts_telegram)", missing)


class S4Hardening(unittest.TestCase):
    def test_csp_present_in_security_headers(self):
        h = security_headers()
        self.assertIn("Content-Security-Policy", h)
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline' ; script", h["Content-Security-Policy"])

    def test_read_json_default_caps_body(self):
        """Default JSON cap is 1MB — the old silent 45MB hole is gone."""
        import inspect

        from amancore.channels import webhook_server as ws

        src = inspect.getsource(ws.WebhookRequestHandler._read_json)
        self.assertIn("max_bytes: int = 1_000_000", src)
        self.assertNotIn("45_000_000", src)


if __name__ == "__main__":
    unittest.main()
