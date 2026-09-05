"""Calendar + consultation-email hooks — offline only (mocked SMTP)."""

import os
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

SCHEMA = "/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql"


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    return con


class IcsTest(unittest.TestCase):
    def test_ics_shape(self):
        from amancore.consultation.calendar import build_ics

        ics = build_ics(
            uid="abc", summary="AmanCode consultation AC-1001",
            description="Service\nhttps://meet",
            location="https://meet", start_utc="2026-09-10T10:00:00+00:00",
            duration_minutes=30, organizer_email="bot@x.com",
            attendee_email="client@x.com")
        for token in ("BEGIN:VCALENDAR", "METHOD:REQUEST", "BEGIN:VEVENT",
                      "DTSTART:20260910T100000Z", "DTEND:20260910T103000Z",
                      "ATTENDEE", "ORGANIZER", "END:VEVENT", "END:VCALENDAR"):
            self.assertIn(token, ics)


class CalendarServiceTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GOOGLE_CALENDAR_ID", None)
        os.environ.pop("GOOGLE_SERVICE_ACCOUNT_FILE", None)

    def test_ics_backend_without_google_creds(self):
        from amancore.consultation.calendar import CalendarService

        con = _db()
        try:
            svc = CalendarService(con)
            self.assertEqual(svc.backend(), "ics")
            res = svc.create_event({
                "id": "c1", "consultation_id": "AC-1001",
                "customer_email": "client@x.com", "service": "متجر",
                "scheduled_at": "2026-09-10T10:00:00+00:00",
                "duration_minutes": 30, "meeting_url": "https://meet/x"})
            self.assertEqual(res["backend"], "ics")
            self.assertIn("BEGIN:VCALENDAR", res["ics"])
            row = con.execute("SELECT calendar_event_id FROM consultations WHERE id='c1'").fetchone()
            # consultations row c1 does not exist; persist must not crash
            self.assertIsNone(row)
        finally:
            con.close()

    def test_ensure_columns_idempotent(self):
        from amancore.consultation.calendar import ensure_columns

        con = _db()
        try:
            ensure_columns(con)
            ensure_columns(con)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(consultations)").fetchall()}
            self.assertIn("calendar_event_id", cols)
            self.assertIn("calendar_link", cols)
        finally:
            con.close()


class BookingEmailHookTest(unittest.TestCase):
    def test_booking_sends_confirmation_email_with_ics(self):
        from amancore.consultation.scheduler import ConsultationScheduler

        con = _db()
        try:
            sched = ConsultationScheduler(con)
            valid = datetime(2026, 9, 2, 14, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
            with patch("amancore.channels.email.send_email") as send:
                res = sched.book_consultation(
                    customer_name="سالم", customer_phone="905551112233",
                    scheduled_at=valid, service="متجر",
                    customer_email="Client@Example.com", language="ar")
            self.assertTrue(res["success"])
            send.assert_called_once()
            to, subject = send.call_args[0][0], send.call_args[0][1]
            self.assertEqual(to, "client@example.com")
            self.assertIn(res["consultation_id"], subject)
            self.assertIn("ics_content", send.call_args[1])
            events = {e["event_type"] for e in con.execute(
                "SELECT event_type FROM consultation_events WHERE consultation_id=?",
                (res["id"],)).fetchall()}
            self.assertIn("CALENDAR_CREATED", events)
            self.assertIn("CONFIRMATION_EMAIL_SENT", events)
        finally:
            con.close()

    def test_booking_without_email_skips_send(self):
        from amancore.consultation.scheduler import ConsultationScheduler

        con = _db()
        try:
            sched = ConsultationScheduler(con)
            valid = datetime(2026, 9, 3, 14, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
            with patch("amancore.channels.email.send_email") as send:
                res = sched.book_consultation(
                    customer_name="سالم", customer_phone="905551112233",
                    scheduled_at=valid)
            self.assertTrue(res["success"])
            send.assert_not_called()
        finally:
            con.close()

    def test_cancel_sends_email_and_cancels_calendar(self):
        from amancore.consultation.scheduler import ConsultationScheduler

        con = _db()
        try:
            sched = ConsultationScheduler(con)
            valid = datetime(2026, 9, 4, 14, 0, tzinfo=ZoneInfo("Asia/Makassar")).astimezone(timezone.utc)
            with patch("amancore.channels.email.send_email"):
                res = sched.book_consultation(
                    customer_name="سالم", customer_phone="905551112233",
                    scheduled_at=valid, customer_email="c@x.com")
            with patch("amancore.channels.email.send_email") as send, \
                 patch("amancore.consultation.calendar.CalendarService.cancel_event",
                       return_value={"backend": "ics", "deleted": None}) as cancel:
                out = sched.cancel_consultation(res["id"], reason="ظرف")
            self.assertTrue(out["success"])
            cancel.assert_called_once()
            send.assert_called_once()
            events = {e["event_type"] for e in con.execute(
                "SELECT event_type FROM consultation_events WHERE consultation_id=?",
                (res["id"],)).fetchall()}
            self.assertIn("CALENDAR_CANCELLED", events)
            self.assertIn("CANCELLATION_EMAIL_SENT", events)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
