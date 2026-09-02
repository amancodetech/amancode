"""Bridge transport contract tests — token auth, error taxonomy, retry
ownership, delivery-uncertainty (owner spec §9/§10/§13/§15/§43/§44)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fixtures.mock_bridge import MockBridge  # noqa: E402

from amancore.channels.bridge_transport import (  # noqa: E402
    BridgeError,
    BridgeTransport,
)


def _config(base_url: str, *, shadow: bool = False) -> dict:
    return {"channel": "whatsapp",
            "bridge": {"base_url": base_url,
                       "token_env": "AMANCODE_BRIDGE_TOKEN",
                       "shadow": shadow,
                       "connect_retries": 1}}


class BridgeTransportTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("AMANCODE_BRIDGE_TOKEN", None)
        os.environ["AMANCODE_BRIDGE_TOKEN"] = "test-bridge-token"

    def tearDown(self):
        os.environ.pop("AMANCODE_BRIDGE_TOKEN", None)
        if self._old is not None:
            os.environ["AMANCODE_BRIDGE_TOKEN"] = self._old

    def test_send_text_success_and_token_header(self):
        bridge = MockBridge()
        try:
            t = BridgeTransport(_config(bridge.base_url))
            result = t.send_message("whatsapp",
                                    {"type": "text", "recipient": "15551234567",
                                     "text": "hello"})
            self.assertTrue(result["accepted"])
            self.assertTrue(result["external_message_id"].startswith("wamid-"))
            self.assertFalse(result["would_send"])
            self.assertEqual(bridge.requests[0]["path"], "/v1/messages/send")
        finally:
            bridge.stop()

    def test_shadow_flag_propagates_would_send(self):
        bridge = MockBridge()
        try:
            t = BridgeTransport(_config(bridge.base_url, shadow=True))
            result = t.send_message("whatsapp",
                                    {"type": "text", "recipient": "15551234567",
                                     "text": "hello"})
            self.assertTrue(result["would_send"])
        finally:
            bridge.stop()

    def test_auth_failure_maps_to_auth_required(self):
        bridge = MockBridge(token="different-token")
        try:
            t = BridgeTransport(_config(bridge.base_url))
            with self.assertRaises(BridgeError) as ctx:
                t.send_message("whatsapp",
                               {"type": "text", "recipient": "1", "text": "x"})
            self.assertEqual(ctx.exception.category, "auth_required")
        finally:
            bridge.stop()

    def test_send_status_500_maps_to_temporary(self):
        bridge = MockBridge(send_status=500)
        try:
            t = BridgeTransport(_config(bridge.base_url))
            with self.assertRaises(BridgeError) as ctx:
                t.send_message("whatsapp",
                               {"type": "text", "recipient": "1", "text": "x"})
            self.assertEqual(ctx.exception.category, "temporary")
        finally:
            bridge.stop()

    def test_unreachable_bridge_is_temporary_after_bounded_retries(self):
        # nothing listens on this port
        t = BridgeTransport(_config("http://127.0.0.1:1"))
        with self.assertRaises(BridgeError) as ctx:
            t.send_message("whatsapp",
                           {"type": "text", "recipient": "1", "text": "x"})
        self.assertEqual(ctx.exception.category, "temporary")

    def test_read_timeout_is_delivery_unknown_never_retryable(self):
        bridge = MockBridge(delay_seconds=2.0)
        try:
            cfg = _config(bridge.base_url)
            cfg["bridge"]["read_timeout"] = 0.2
            cfg["bridge"]["connect_retries"] = 0
            t = BridgeTransport(cfg)
            with self.assertRaises(BridgeError) as ctx:
                t.send_message("whatsapp",
                               {"type": "text", "recipient": "1", "text": "x"})
            self.assertEqual(ctx.exception.category, "delivery_unknown")
            self.assertNotIn(ctx.exception.category, ("temporary", "provider"))
        finally:
            bridge.stop()

    def test_probe_timeout_is_temporary_not_delivery_unknown(self):
        bridge = MockBridge(delay_seconds=2.0)
        try:
            cfg = _config(bridge.base_url)
            cfg["bridge"]["read_timeout"] = 0.2
            t = BridgeTransport(cfg)
            with self.assertRaises(BridgeError) as ctx:
                t.health()
            self.assertEqual(ctx.exception.category, "temporary")
        finally:
            bridge.stop()

    def test_health_and_sessions(self):
        bridge = MockBridge(session_state="AUTH_REQUIRED")
        try:
            t = BridgeTransport(_config(bridge.base_url))
            self.assertTrue(t.health().get("ok"))
            sessions = t.sessions()
            self.assertEqual(
                sessions["sessions"]["whatsapp"]["state"], "AUTH_REQUIRED")
        finally:
            bridge.stop()

    def test_media_upload_download_roundtrip(self):
        bridge = MockBridge()
        try:
            t = BridgeTransport(_config(bridge.base_url))
            media_id = t.upload_media(b"binary-bytes", "image/png", "x.png")
            self.assertTrue(media_id.startswith("media-"))
            data, _ = t.download_media(media_id)
            self.assertEqual(data, b"binary-bytes")
        finally:
            bridge.stop()

    def test_health_probe_fail_soft_never_raises(self):
        from amancore.channels.bridge_transport import bridge_health_probe
        # unreachable bridge → DOWN dict, no exception
        state = bridge_health_probe(_config("http://127.0.0.1:1"))
        self.assertEqual(state["process"], "DOWN")
        bridge = MockBridge()
        try:
            state = bridge_health_probe(_config(bridge.base_url))
            self.assertEqual(state["process"], "UP")
            self.assertEqual(state["session"], "CONNECTED")
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
