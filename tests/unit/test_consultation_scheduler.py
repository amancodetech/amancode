import sqlite3
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from amancore.consultation.scheduler import ConsultationScheduler

class TestConsultationScheduler(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.scheduler = ConsultationScheduler(self.con)

    def tearDown(self):
        self.con.close()

    def test_book_consultation_success(self):
        valid_dt = datetime(2026, 9, 1, 14, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        res = self.scheduler.book_consultation(
            customer_name="سالم",
            customer_phone="905551112233",
            scheduled_at=valid_dt,
            service="تطوير متجر إلكتروني",
            meeting_type="GOOGLE_MEET",
            language="ar"
        )
        self.assertTrue(res["success"])
        self.assertIn("AC-", res["consultation_id"])
        self.assertIn("meet.google.com", res["meeting_url"])
        self.assertIn("سالم", res["confirmation_message"])

        # Check DB record
        row = self.con.execute("SELECT * FROM consultations WHERE consultation_id = ?", (res["consultation_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["customer_name"], "سالم")
        self.assertEqual(row["status"], "CONFIRMED")

        # Check audit event log
        events = self.con.execute("SELECT * FROM consultation_events WHERE consultation_id = ?", (res["id"],)).fetchall()
        event_types = [e["event_type"] for e in events]
        self.assertIn("CREATED", event_types)
        self.assertIn("CONFIRMED", event_types)
        self.assertIn("MEETING_LINK_CREATED", event_types)

    def test_book_consultation_duplicate_rejected(self):
        valid_dt = datetime(2026, 9, 1, 14, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        res1 = self.scheduler.book_consultation(
            customer_name="سالم",
            customer_phone="905551112233",
            scheduled_at=valid_dt
        )
        self.assertTrue(res1["success"])

        # Second booking at exact same slot must be rejected
        res2 = self.scheduler.book_consultation(
            customer_name="خالد",
            customer_phone="905559998877",
            scheduled_at=valid_dt
        )
        self.assertFalse(res2["success"])
        self.assertEqual(res2["error"], "SLOT_UNAVAILABLE")

    def test_cancel_consultation(self):
        valid_dt = datetime(2026, 9, 1, 15, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        res = self.scheduler.book_consultation(
            customer_name="طارق",
            customer_phone="905551112233",
            scheduled_at=valid_dt
        )
        cid = res["consultation_id"]

        cancel_res = self.scheduler.cancel_consultation(cid)
        self.assertTrue(cancel_res["success"])

        row = self.con.execute("SELECT * FROM consultations WHERE consultation_id = ?", (cid,)).fetchone()
        self.assertEqual(row["status"], "CANCELLED")

        # Cancel event recorded
        evt = self.con.execute("SELECT * FROM consultation_events WHERE consultation_id = ? AND event_type = 'CANCELLED'", (res["id"],)).fetchone()
        self.assertIsNotNone(evt)

if __name__ == "__main__":
    unittest.main()
