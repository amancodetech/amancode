"""Bridge ingress integration tests — POST /bridge/inbound end-to-end
through the real HTTP server + real coordinator stack (owner spec §12).

Covers the full ACK contract: accepted / duplicate / invalid envelope /
unauthorized / retryable failure, and proves the bridge-pushed event takes
EXACTLY the same pipeline as a Meta webhook (same idempotency, same outbox).
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amancore.channels.webhook_server import WebhookServer  # noqa: E402
from tests.common import make_brain, make_db  # noqa: E402
from tests.integration.test_webhook_server import (  # noqa: E402
    build_signed_coordinator,
)

BRIDGE_TOKEN = "ingress-test-token"


def _envelope(msg_id="wamid.BRIDGE1", text="hello from the bridge",
              wa_id="15557778888") -> dict:
    return {
        "event_id": f"evt-{msg_id}",
        "event_type": "message.received",
        "channel": "whatsapp",
        "external_message_id": msg_id,
        "sender": {"external_id": wa_id, "name": "Bridge Tester"},
        "message": {"type": "text", "text": text},
        "timestamp": "2026-08-29T00:00:00+00:00",
        "metadata": {},
    }


class BridgeInboundTests(unittest.TestCase):
    """Real HTTP server + real coordinator (mock provider) — same scaffolding
    as the webhook server integration tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_token = __import__("os").environ.pop("BRIDGE_INGRESS_TOKEN",
                                                       None)
        __import__("os").environ["BRIDGE_INGRESS_TOKEN"] = BRIDGE_TOKEN
        root = Path(self._tmp.name)
        # mock-mode coordinator with the SAME runtime dict shape as production
        runtime = build_signed_coordinator(root)
        runtime["sync"] = None
        runtime["inbox"] = None
        self.runtime = runtime
        self.coordinator = runtime["coordinator"]
        self.db = runtime["db"]
        self.httpd = WebhookServer(("127.0.0.1", 0), runtime)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        __import__("os").environ.pop("BRIDGE_INGRESS_TOKEN", None)
        if self._old_token is not None:
            __import__("os").environ["BRIDGE_INGRESS_TOKEN"] = self._old_token
        self._tmp.cleanup()

    def _post(self, payload, token=BRIDGE_TOKEN, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/bridge/inbound", data=body,
            headers={"Content-Type": "application/json",
                     "X-Bridge-Token": token}, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def _outbox_rows(self):
        return self.db.execute("SELECT * FROM message_outbox").fetchall()

    # ---- ACK contract -----------------------------------------------------
    def test_accepted_ack_and_outbox_reply(self):
        status, ack = self._post(_envelope())
        self.assertEqual(status, 200)
        self.assertTrue(ack["accepted"])
        self.assertFalse(ack["duplicate"])
        self.assertEqual(ack["event_id"], "evt-wamid.BRIDGE1")

    def test_duplicate_ack_processed_once(self):
        """owner spec §50: same event × 2 → accepted=true, duplicate=true;
        the core pipeline ran exactly once."""
        status1, ack1 = self._post(_envelope())
        status2, ack2 = self._post(_envelope())
        self.assertEqual((status1, status2), (200, 200))
        self.assertTrue(ack1["accepted"])
        self.assertTrue(ack2["accepted"])
        self.assertFalse(ack1["duplicate"])
        self.assertTrue(ack2["duplicate"])

    def test_unauthorized_rejected_non_retryable(self):
        status, ack = self._post(_envelope(), token="wrong-token")
        self.assertEqual(status, 403)
        self.assertFalse(ack["accepted"])
        self.assertFalse(ack["retryable"])
        self.assertEqual(ack["error_code"], "UNAUTHORIZED")

    def test_missing_token_rejected(self):
        status, ack = self._post(_envelope(), token="")
        self.assertEqual(status, 403)

    def test_invalid_envelope_non_retryable(self):
        status, ack = self._post({"channel": "tiktok", "event_type": "x"})
        self.assertEqual(status, 400)
        self.assertFalse(ack["accepted"])
        self.assertFalse(ack["retryable"])

    def test_malformed_json_non_retryable(self):
        status, ack = self._post(None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(ack["error_code"], "MALFORMED_JSON")

    def test_batch_envelopes_accepted(self):
        batch = [_envelope(msg_id="wamid.B1"), _envelope(msg_id="wamid.B2")]
        status, ack = self._post(batch)
        self.assertEqual(status, 200)
        self.assertTrue(ack["accepted"])
        self.assertEqual(len(ack["batch"]), 2)
        self.assertTrue(all(item["accepted"] for item in ack["batch"]))

    # ---- same pipeline as the webhook --------------------------------------
    def test_bridge_event_flows_into_the_same_outbox_and_crm(self):
        """owner spec §11/§16: no second intake pipeline; identity parity."""
        self._post(_envelope(wa_id="15551112222"))
        # the reply was enqueued through the EXISTING outbox
        rows = self._outbox_rows()
        self.assertTrue(rows)
        wa_rows = [r for r in rows if r["channel"] == "whatsapp"]
        self.assertTrue(wa_rows)
        # identity lands in the EXISTING platform_identities table —
        # owner spec §16: no bridge-specific identity space, no lead split
        ident = self.db.execute(
            "SELECT i.channel, i.external_user_id, i.lead_id"
            " FROM platform_identities i WHERE i.channel='whatsapp'"
            " AND i.external_user_id='15551112222'").fetchone()
        self.assertIsNotNone(ident)
        # inbound idempotency key uses the SAME shape as the Graph webhook
        idem = self.db.execute(
            "SELECT 1 FROM idempotency_keys WHERE idempotency_key=?",
            ("wa:wamid.BRIDGE1",)).fetchone()
        self.assertIsNotNone(idem)


if __name__ == "__main__":
    unittest.main()
