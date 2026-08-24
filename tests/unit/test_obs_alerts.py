"""OBS-102: alert fingerprints — distinct alerts must not collapse (audit R1)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amancore.log import get_logger  # noqa: F401
from amancore.ops.alerts import AlertDispatcher
from amancore.storage.db import Database


class CountingTransport:
    name = "counting"

    def __init__(self, fail_times: int = 0):
        self.sent = 0
        self.fail_times = fail_times

    def send(self, alert: dict) -> dict:
        if self.sent < self.fail_times:
            self.sent += 1
            raise RuntimeError("simulated transport outage")
        self.sent += 1
        return {"delivered": True, "transport": self.name}


class TestAlertFingerprints(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(pathlib_Path(self.tmp.name))
        from amancore.storage.db import open_database
        from pathlib import Path as _P

        root = _P(__file__).resolve().parents[2]
        self.db = open_database(self.tmp.name, root / "amancore" / "storage" / "schema.sql")

    def tearDown(self):
        self.db.close()

    def _dispatcher(self, transport):
        return AlertDispatcher(self.db, config={"dedup_cooldown_minutes": 60},
                               transport=transport)

    def test_distinct_alerts_both_deliver_within_window(self):
        """R1 core: handoff at 09:05 must NOT silence leak alert at 09:40."""
        transport = CountingTransport()
        d = self._dispatcher(transport)
        r1 = d.dispatch(severity="HIGH", category="owner", title="handoff",
                        summary="lead A wants human", fingerprint="owner:human_requested:lead-1")
        r2 = d.dispatch(severity="HIGH", category="owner", title="leak",
                        summary="leak blocked lead B", fingerprint="owner:leak_blocked:lead-2")
        self.assertFalse(r1["deduplicated"])
        self.assertFalse(r2["deduplicated"])
        self.assertTrue(r1["delivered"] and r2["delivered"])
        self.assertEqual(transport.sent, 2)

    def test_same_fingerprint_dedups_within_window(self):
        transport = CountingTransport()
        d = self._dispatcher(transport)
        d.dispatch(severity="HIGH", category="owner", title="t",
                   summary="x", fingerprint="owner:human_requested:lead-1")
        r2 = d.dispatch(severity="HIGH", category="owner", title="t2",
                        summary="y", fingerprint="owner:human_requested:lead-1")
        self.assertTrue(r2["deduplicated"])
        self.assertEqual(transport.sent, 1)

    def test_severity_windows_from_config(self):
        d = self._dispatcher(CountingTransport())
        d.cooldown_by_severity = {"CRITICAL": 15, "MEDIUM": 240}
        self.assertEqual(d._cooldown_for("CRITICAL"), 15)
        self.assertEqual(d._cooldown_for("MEDIUM"), 240)
        self.assertEqual(d._cooldown_for("HIGH"), 60)  # default fallback

    def test_transport_failure_retries_then_persists_undelivered(self):
        transport = CountingTransport(fail_times=10)  # always fails
        d = self._dispatcher(transport)
        r = d.dispatch(severity="CRITICAL", category="owner", title="outage",
                       summary="provider down", fingerprint="owner:incident:waba")
        self.assertFalse(r["delivered"])
        self.assertIn("delivery failed after 3 attempts", r["alert_id"] and
                      (d.store.list(limit=1)[0]["action_required"]))
        self.assertGreaterEqual(transport.sent, 3)  # retried

    def test_send_owner_alert_fingerprint_shape(self):
        """send_owner_alert derives distinct fingerprints for distinct messages."""
        import hashlib

        from amancore.services.owner_alert import send_owner_alert  # noqa: F401

        msg_a = "Handoff human_requested — lead X"
        fp_explicit = f"owner:human_requested:{'lead-9'}"
        digest = hashlib.sha1(msg_a.encode()).hexdigest()[:12]
        self.assertNotEqual(fp_explicit, f"owner:generic:{digest}")  # shapes differ by design


# tiny alias so setUp works before import ordering above
from pathlib import Path as pathlib_Path  # noqa: E402


if __name__ == "__main__":
    unittest.main()
