import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from amancore.leads.followup_engine import HonestLeadFollowupEngine

class TestHonestLeadFollowupEngine(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.engine = HonestLeadFollowupEngine(self.con)

    def tearDown(self):
        self.con.close()

    def test_message_is_truthful_and_consultative(self):
        lead = {
            "name": "أحمد",
            "service_interest": "تطوير متجر إلكتروني وتطبيق",
        }
        msg = self.engine.generate_message(lead)
        self.assertIn("أحمد", msg)
        # Verify no false claims about prior fictitious projects
        self.assertNotIn("نفذناها", msg)
        self.assertNotIn("سابقة", msg)
        self.assertIn("أمان كود", msg)

    def test_dormant_lead_detection_and_execution(self):
        now = datetime.now(timezone.utc)
        dormant_time = (now - timedelta(hours=36)).isoformat()

        self.con.execute(
            """
            INSERT INTO leads (lead_id, name, service_interest, contact_whatsapp, last_contact_at, created_at, updated_at)
            VALUES ('lead_test_99', 'خالد', 'تصميم هوية بصرية', '905551112233', ?, ?, ?)
            """,
            (dormant_time, dormant_time, dormant_time)
        )
        self.con.commit()

        pending = self.engine.get_pending_followups()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["lead_id"], "lead_test_99")

        # Execute followup
        res = self.engine.execute_followup("lead_test_99")
        self.assertTrue(res["success"])

        # After execution, next_followup_at is advanced by 7 days so it will not be pending again
        pending_after = self.engine.get_pending_followups()
        self.assertEqual(len(pending_after), 0)

if __name__ == "__main__":
    unittest.main()
