import sqlite3
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from amancore.consultation.availability import AvailabilityEngine

class TestConsultationAvailability(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.engine = AvailabilityEngine(self.con)

    def tearDown(self):
        self.con.close()

    def test_working_hours_validation(self):
        # 09:00 AM (Outside 10:00 - 20:00 in Asia/Makassar)
        early_dt = datetime(2026, 9, 1, 9, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        self.assertFalse(self.engine.is_slot_available(early_dt))

        # 11:00 AM (Inside 10:00 - 20:00 in Asia/Makassar)
        valid_dt = datetime(2026, 9, 1, 11, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        self.assertTrue(self.engine.is_slot_available(valid_dt))

        # 21:00 PM (Outside 10:00 - 20:00 in Asia/Makassar)
        late_dt = datetime(2026, 9, 1, 21, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        self.assertFalse(self.engine.is_slot_available(late_dt))

    def test_conflict_detection(self):
        slot_dt = datetime(2026, 9, 1, 11, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        slot_iso = slot_dt.isoformat()

        # Insert a confirmed consultation
        self.con.execute(
            """
            INSERT INTO consultations (id, consultation_id, customer_name, scheduled_at, duration_minutes, status, created_at, updated_at)
            VALUES ('c1', 'AC-1001', 'Test Client', ?, 30, 'CONFIRMED', ?, ?)
            """,
            (slot_iso, slot_iso, slot_iso)
        )
        self.con.commit()

        # Same slot is now unavailable
        self.assertFalse(self.engine.is_slot_available(slot_dt))

        # Slot overlapping within duration + buffer (e.g. 11:15) is unavailable
        overlap_dt = datetime(2026, 9, 1, 11, 15, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        self.assertFalse(self.engine.is_slot_available(overlap_dt))

        # Slot after buffer (e.g. 11:40) is available
        free_dt = datetime(2026, 9, 1, 11, 40, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
        self.assertTrue(self.engine.is_slot_available(free_dt))

    def test_get_available_slots_returns_list(self):
        slots = self.engine.get_available_slots("2026-09-01")
        self.assertIsInstance(slots, list)
        self.assertTrue(len(slots) > 5)
        self.assertIn("10:00", slots)
        self.assertIn("10:40", slots)

if __name__ == "__main__":
    unittest.main()
