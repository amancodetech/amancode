import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from amancore.consultation.reminders import ConsultationReminderService

class TestConsultationReminders(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.service = ConsultationReminderService(self.con)

    def tearDown(self):
        self.con.close()

    def test_reminders_60m_and_15m_idempotent(self):
        now = datetime.now(timezone.utc)
        in_50m = (now + timedelta(minutes=50)).isoformat()
        in_10m = (now + timedelta(minutes=10)).isoformat()

        # Insert consultation starting in 50 minutes (should get 60m reminder)
        self.con.execute(
            """
            INSERT INTO consultations (id, consultation_id, customer_name, customer_phone, scheduled_at, status, created_at, updated_at)
            VALUES ('c_60', 'AC-2001', 'أحمد', '905551112233', ?, 'CONFIRMED', ?, ?)
            """,
            (in_50m, now.isoformat(), now.isoformat())
        )

        # Insert consultation starting in 10 minutes (should get 15m reminder)
        self.con.execute(
            """
            INSERT INTO consultations (id, consultation_id, customer_name, customer_phone, scheduled_at, status, created_at, updated_at)
            VALUES ('c_15', 'AC-2002', 'سامر', '905551112233', ?, 'CONFIRMED', ?, ?)
            """,
            (in_10m, now.isoformat(), now.isoformat())
        )
        self.con.commit()

        # First run: should send 1 for 60m and 1 for 15m
        res1 = self.service.check_and_send_reminders()
        self.assertEqual(res1["sent_60m"], 1)
        self.assertEqual(res1["sent_15m"], 1)

        # Second run immediately after: Idempotency check -> 0 sent!
        res2 = self.service.check_and_send_reminders()
        self.assertEqual(res2["sent_60m"], 0)
        self.assertEqual(res2["sent_15m"], 0)

if __name__ == "__main__":
    unittest.main()
