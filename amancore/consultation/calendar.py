"""CalendarService — consultations get a real calendar event + invite.

Two backends, chosen at call time (no config branching at import):
- Google Calendar (preferred when GOOGLE_CALENDAR_ID +
  GOOGLE_SERVICE_ACCOUNT_FILE are set and the calendar is shared with the
  service account): insert event with attendee + Hangouts Meet link
  passthrough, store event id/link on the consultation row.
- ICS fallback (zero creds): build an RFC5545 invite string that booking
  and reminders attach to the confirmation email. The customer taps it
  and the event lands in Apple/Google/Outlook calendar.

Schema: consultations gains calendar_event_id + calendar_link via
ensure_columns() (ALTER TABLE, duplicate-column-safe) — plus the same
columns in schema.sql for fresh installs.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from ..ids import new_id
from ..log import get_logger

log = get_logger("consultation.calendar")

GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar"


def ensure_columns(db) -> None:
    """Add calendar columns if missing (safe to call on every booking)."""
    if db is None:
        return
    cols = {r["name"] for r in db.execute("PRAGMA table_info(consultations)").fetchall()}
    for col in ("calendar_event_id", "calendar_link"):
        if col not in cols:
            try:
                db.execute(f"ALTER TABLE consultations ADD COLUMN {col} TEXT")
            except Exception as exc:  # noqa: BLE001 — race-safe
                log.warning("ensure_columns %s: %s", col, exc)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        pass


def _as_utc(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_ics(*, uid: str, summary: str, description: str, location: str,
              start_utc: datetime | str, duration_minutes: int = 30,
              organizer_email: str = "", attendee_email: str = "") -> str:
    """Minimal RFC5545 REQUEST invite (no third-party dependency)."""
    start = _as_utc(start_utc)
    end = start + timedelta(minutes=int(duration_minutes or 30))
    fmt = lambda d: d.strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda s: str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//AmanCode//Consultations//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}@amancode",
        f"DTSTAMP:{now}",
        f"DTSTART:{fmt(start)}",
        f"DTEND:{fmt(end)}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(description)}",
        f"LOCATION:{esc(location)}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
    ]
    if organizer_email:
        lines.append(f"ORGANIZER;CN=AmanCode:mailto:{organizer_email}")
    if attendee_email:
        lines.append(f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{attendee_email}")
    lines += ["END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(lines)


def _google_client():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if not sa_file:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE not set")
    creds = service_account.Credentials.from_service_account_file(
        sa_file, scopes=[GOOGLE_SCOPE])
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class CalendarService:
    """Create/cancel calendar events for consultations."""

    def __init__(self, db=None):
        self.db = db

    def backend(self) -> str:
        if os.environ.get("GOOGLE_CALENDAR_ID") and os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE"):
            return "google"
        return "ics"

    def create_event(self, consultation: dict) -> dict:
        """Create event for a consultation row dict. Returns backend+ids+ics."""
        ensure_columns(self.db)
        start = _as_utc(consultation["scheduled_at"])
        duration = int(consultation.get("duration_minutes") or 30)
        summary = f"AmanCode consultation {consultation.get('consultation_id', '')}".strip()
        description = (
            f"Service: {consultation.get('service', '')}\n"
            f"Booking: #{consultation.get('consultation_id', '')}\n"
            f"Meeting: {consultation.get('meeting_url', '')}\n"
        )
        organizer = os.environ.get("SMTP_USER", "")
        attendee = str(consultation.get("customer_email") or "")
        uid = str(consultation.get("id") or new_id())
        ics = build_ics(uid=uid, summary=summary, description=description,
                        location=str(consultation.get("meeting_url") or ""),
                        start_utc=start, duration_minutes=duration,
                        organizer_email=organizer, attendee_email=attendee)
        result: dict = {"backend": "ics", "event_id": None, "link": None, "ics": ics}
        if self.backend() == "google":
            try:
                service = _google_client()
                body = {
                    "summary": summary,
                    "description": description,
                    "location": str(consultation.get("meeting_url") or ""),
                    "start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": (start + timedelta(minutes=duration)).isoformat()},
                    "attendees": ([{"email": attendee}] if attendee else []),
                }
                created = service.events().insert(
                    calendarId=os.environ["GOOGLE_CALENDAR_ID"],
                    body=body, sendUpdates="all" if attendee else "none").execute()
                result.update({"backend": "google",
                               "event_id": created.get("id"),
                               "link": created.get("htmlLink")})
                log.info("google event created %s", created.get("id"))
            except Exception as exc:  # noqa: BLE001 — ICS still returned
                log.warning("google create failed, ICS fallback: %s", exc)
        self._persist(consultation.get("id"), result)
        return result

    def cancel_event(self, consultation_id: str) -> dict:
        """Delete the Google event (if any). ICS needs no server delete."""
        row = None
        if self.db is not None:
            try:
                ensure_columns(self.db)
                row = self.db.execute(
                    "SELECT id, calendar_event_id FROM consultations WHERE id = ? OR consultation_id = ?",
                    (consultation_id, consultation_id)).fetchone()
            except Exception:  # noqa: BLE001
                row = None
        event_id = (dict(row).get("calendar_event_id") if row else "") or ""
        if event_id and self.backend() == "google":
            try:
                _google_client().events().delete(
                    calendarId=os.environ["GOOGLE_CALENDAR_ID"],
                    eventId=event_id, sendUpdates="all").execute()
                log.info("google event deleted %s", event_id)
                return {"backend": "google", "deleted": event_id}
            except Exception as exc:  # noqa: BLE001
                log.warning("google delete failed: %s", exc)
                return {"backend": "google", "deleted": None, "error": str(exc)[:150]}
        return {"backend": self.backend(), "deleted": None}

    def _persist(self, row_id: str | None, result: dict) -> None:
        if self.db is None or not row_id:
            return
        try:
            self.db.execute(
                "UPDATE consultations SET calendar_event_id = ?, calendar_link = ?, updated_at = ? WHERE id = ?",
                (result.get("event_id"), result.get("link"),
                 datetime.now(timezone.utc).isoformat(), row_id))
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar persist failed: %s", exc)
