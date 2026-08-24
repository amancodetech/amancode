"""DB-301: schema parity — hot-path indexes must exist on FRESH deploys (D3).

Guards against the audit scenario: indexes created manually in prod but
missing from schema.sql → next deployment silently regresses to full scans.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amancore.storage.db import open_database  # noqa: E402

SCHEMA = ROOT / "amancore" / "storage" / "schema.sql"

HOT_INDEXES = {
    "idx_channel_messages_wa": "channel_messages",
    "idx_channel_messages_dir": "channel_messages",
    "idx_channel_messages_lead": "channel_messages",
    "idx_leads_whatsapp": "leads",
    "idx_conversations_last_msg": "conversations",
    "idx_outbox_ready": "message_outbox",
    "uq_channel_messages_wamid": "channel_messages",
}


class FreshDeployParity(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "storage" / "_test_db301_fresh.db"
        self.path.unlink(missing_ok=True)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def _fresh(self):
        return open_database(self.path, schema_file=SCHEMA)

    def test_all_hot_indexes_on_fresh_database(self):
        db = self._fresh()
        try:
            names = {r["name"] for r in
                     db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
            for idx in HOT_INDEXES:
                self.assertIn(idx, names, f"{idx} missing from fresh deploy")
        finally:
            db.close()

    def test_planner_uses_indexes_for_hot_queries(self):
        db = self._fresh()
        try:
            plans = " ".join(
                r["detail"] for r in db.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM channel_messages "
                    "WHERE wa_id='x' AND direction='in'"
                ).fetchall()
            ) + " " + " ".join(
                r["detail"] for r in db.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM leads WHERE contact_whatsapp='y'"
                ).fetchall()
            )
            self.assertGreaterEqual(plans.count("USING INDEX"), 2)
        finally:
            db.close()

    def test_pragmas_active(self):
        db = self._fresh()
        try:
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode, "wal")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
