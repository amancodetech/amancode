import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from amancore.analytics.briefing import ExecutiveBriefingService

class TestExecutiveBriefing(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.service = ExecutiveBriefingService(self.con)

    def tearDown(self):
        self.con.close()

    def test_gather_metrics_empty_db(self):
        metrics = self.service.gather_metrics()
        self.assertEqual(metrics["leads_today"], 0)
        self.assertEqual(metrics["leads_this_week"], 0)
        self.assertEqual(metrics["meetings"]["today_booked"], 0)
        self.assertEqual(metrics["leads_dod"], "0%")

    def test_gather_metrics_with_data(self):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        yesterday_iso = (now - timedelta(days=1)).isoformat()

        # Insert leads
        self.con.execute(
            "INSERT INTO leads (lead_id, name, service_interest, created_at, updated_at) VALUES ('l1', 'Ahmed', 'تصميم متجر وموقع', ?, ?)",
            (now_iso, now_iso)
        )
        self.con.execute(
            "INSERT INTO leads (lead_id, name, service_interest, created_at, updated_at) VALUES ('l2', 'Khaled', 'هوية بصرية وشعار', ?, ?)",
            (yesterday_iso, yesterday_iso)
        )

        # Insert channel messages
        self.con.execute(
            "INSERT INTO channel_messages (channel, direction, external_user_id, body, created_at) VALUES ('whatsapp', 'in', 'user_1', 'Hi', ?)",
            (now_iso,)
        )

        # Insert consultation
        self.con.execute(
            """
            INSERT INTO consultations (id, consultation_id, customer_name, scheduled_at, status, created_at, updated_at)
            VALUES ('c1', 'AC-1001', 'Ahmed', ?, 'CONFIRMED', ?, ?)
            """,
            (now_iso, now_iso, now_iso)
        )
        self.con.commit()

        metrics = self.service.gather_metrics()
        self.assertEqual(metrics["leads_today"], 1)
        self.assertEqual(metrics["leads_yesterday"], 1)
        self.assertEqual(metrics["leads_this_week"], 2)
        self.assertEqual(metrics["categories"]["Website"], 1)
        self.assertEqual(metrics["categories"]["Branding"], 1)
        self.assertEqual(metrics["comm"]["whatsapp"], 1)
        self.assertEqual(metrics["comm"]["inbound"], 1)
        self.assertEqual(metrics["meetings"]["today_booked"], 1)

    def test_format_telegram_briefing_renders_text(self):
        report = self.service.format_telegram_briefing()
        self.assertIn("AmanCode Executive Briefing", report)
        self.assertIn("LEADS & CLIENTS", report)
        self.assertIn("COMMUNICATION", report)
        self.assertIn("CONSULTATIONS", report)

if __name__ == "__main__":
    unittest.main()
