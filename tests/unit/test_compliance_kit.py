"""Compliance kit (post-ban guardrails): ConsentGate, SendValve, TemplateLock,
compliance-gated followups, worker tier hold."""

import sys
import unittest
from datetime import datetime, timedelta, timezone as tz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.compliance.guard import ConsentGate, SendValve, TemplateLock  # noqa: E402
from tests._db import fresh_db, wipe  # noqa: E402


class Harness(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db()
        wipe(self.db)

    def tearDown(self):
        self.db.close()


def mklead(db, lid="L1", consent=True, opt_out=0):
    now = datetime.now(tz.utc).isoformat()
    db.execute(
        "INSERT INTO leads (lead_id, lead_stage, contact_whatsapp, opt_out,"
        " consent_at, consent_source, created_at, updated_at)"
        " VALUES (?, 'nurture', '905000000001', ?, ?, ?, ?, ?)",
        (lid, opt_out, now if consent else None,
         "inbound_first_message" if consent else None, now, now))
    db.commit()
    row = db.execute("SELECT * FROM leads WHERE lead_id=?", (lid,)).fetchone()
    return dict(row)


class ConsentGateTests(Harness):
    def test_no_consent_blocked(self):
        lead = mklead(self.db, consent=False)
        ok, why = ConsentGate.can_initiate(lead)
        self.assertFalse(ok)
        self.assertEqual(why, "no_recorded_consent")

    def test_consented_allowed(self):
        lead = mklead(self.db, consent=True)
        ok, why = ConsentGate.can_initiate(lead)
        self.assertTrue(ok); self.assertEqual(why, "ok")

    def test_opt_out_wins_even_with_consent(self):
        lead = mklead(self.db, consent=True, opt_out=1)
        ok, why = ConsentGate.can_initiate(lead)
        self.assertFalse(ok); self.assertEqual(why, "opted_out")


class ValveTests(Harness):
    def _seed_sent(self, n, initiated=False):
        now = datetime.now(tz.utc).isoformat()
        for i in range(n):
            self.db.execute(
                "INSERT INTO message_outbox (message_id, channel, recipient,"
                " message_type, payload, status, created_at, sent_at, initiation)"
                " VALUES (?, 'whatsapp', ?, 'text', '{}', 'sent', ?, ?, ?)",
                (f"m{i}-{time_ns()}", f"905{i:011d}", now, now,
                 "yes" if initiated else None))
        self.db.commit()

    def test_tier_ceiling_blocks_everything(self):
        v = SendValve(self.db, tiers=[3, 250], tier_index=0, auto_cap=100)
        self._seed_sent(3)
        ok, why = v.check_all_outbound(1)
        self.assertFalse(ok); self.assertIn("warmup_tier_cap", why)

    def test_auto_cap_blocks_initiation_only(self):
        v = SendValve(self.db, tiers=[500], tier_index=0, auto_cap=2)
        self._seed_sent(2, initiated=True)
        ok, why = v.check_initiation(1)
        self.assertFalse(ok); self.assertIn("auto_cap", why)
        # customer replies still allowed under same usage
        self._seed_sent(0)
        ok2, _ = v.check_all_outbound(1)
        self.assertTrue(ok2)

    def test_manual_approval_raises_today_only(self):
        v = SendValve(self.db, tiers=[500], tier_index=0, auto_cap=2)
        self._seed_sent(2, initiated=True)
        self.assertFalse(v.check_initiation(1)[0])
        v.approve_today(5)
        self.assertTrue(v.check_initiation(1)[0])
        self.assertGreaterEqual(v.approved_extra_today(), 5)

    def test_reserve_stops_at_cap(self):
        v = SendValve(self.db, tiers=[500], tier_index=0, auto_cap=3)
        granted, _ = v.reserve_initiations(5)
        self.assertEqual(granted, 3)


def time_ns():
    import time
    return time.time_ns()


class TemplateLockTests(unittest.TestCase):
    def test_empty_allowlist_blocks_all(self):
        self.assertIsNone(TemplateLock({}).resolve("followup"))

    def test_registered_template_resolves(self):
        tl = TemplateLock({"followup": {"name": "followup_v1", "language": "ar"}})
        t = tl.resolve("followup")
        self.assertEqual(t["name"], "followup_v1")


class FollowupsGated(Harness):
    def _registry_followups(self):
        from amancore.ops.registry import JobRegistry

        cfg = type("C", (), {"retention": {}, "database_path": "x",
                             "app": {"compliance": {"approved_templates":
                                     {"followup": {"name": "f1", "language": "ar"}}}}})()
        return JobRegistry(self.db, config=cfg, root=ROOT).handlers()["followups.check"]

    def _seed_due_lead(self, lid="L9", consent=True):
        now = datetime.now(tz.utc)
        self.db.execute(
            "INSERT INTO leads (lead_id, lead_stage, name, contact_whatsapp, opt_out,"
            " next_followup_at, consent_at, created_at, updated_at)"
            " VALUES (?, 'nurture', 'T', '905321112233', 0, ?, ?, ?, ?)",
            (lid, (now - timedelta(days=1)).isoformat(),
             now.isoformat() if consent else None, now.isoformat(), now.isoformat()))
        self.db.commit()

    def test_no_template_configured_zero_sends(self):
        from amancore.ops.registry import JobRegistry

        cfg = type("C", (), {"retention": {}, "database_path": "x",
                             "app": {"compliance": {}}})()
        h = JobRegistry(self.db, config=cfg, root=ROOT).handlers()["followups.check"]
        res = h({})
        self.assertEqual(res.get("enqueued"), 0)

    def test_gated_flow_counts_consent_skips(self):
        self._seed_due_lead("L9c", consent=True)
        self._seed_due_lead("L9n", consent=False)
        res = self._registry_followups()({})
        self.assertEqual(res["enqueued"], 1)          # only the consented one
        self.assertEqual(res["skipped_no_consent"], 1)
        tag = self.db.execute(
            "SELECT initiation FROM message_outbox WHERE idempotency_key"
            " LIKE 'followup:L9c:%'").fetchone()["initiation"]
        self.assertEqual(tag, "yes")


if __name__ == "__main__":
    unittest.main()
