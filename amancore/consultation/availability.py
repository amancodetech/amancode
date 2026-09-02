"""AvailabilityEngine — Single Source of Truth for consultation slots.

Guarantees:
- Strict validation against working hours (default: 10:00 - 20:00).
- Configurable timezone (default: Asia/Makassar).
- Strict conflict prevention & overlap detection (with buffer).
- No hallucinations: slots are derived from actual DB state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..log import get_logger

log = get_logger("consultation.availability")


class AvailabilityEngine:
    """Calculates and checks true slot availability against working hours and DB state."""

    def __init__(self, db, config: dict | None = None):
        self.db = db
        cfg = config or {}
        consultation_cfg = cfg.get("consultation") or {}

        tz_name = consultation_cfg.get("timezone", "Asia/Makassar")
        try:
            self.tz = ZoneInfo(tz_name)
            self.tz_name = tz_name
        except Exception:
            self.tz = timezone.utc
            self.tz_name = "UTC"

        wh = consultation_cfg.get("working_hours", {})
        self.start_hour = int(wh.get("start", "10:00").split(":")[0])
        self.start_minute = int(wh.get("start", "10:00").split(":")[1])
        self.end_hour = int(wh.get("end", "20:00").split(":")[0])
        self.end_minute = int(wh.get("end", "20:00").split(":")[1])

        self.duration_minutes = int(consultation_cfg.get("duration_minutes", 30))
        self.buffer_minutes = int(consultation_cfg.get("buffer_minutes", 10))

    def is_slot_available(self, scheduled_at_utc: datetime | str, duration_minutes: int | None = None) -> bool:
        """Deterministic check ensuring a slot is within working hours and has no DB overlap."""
        if isinstance(scheduled_at_utc, str):
            dt = datetime.fromisoformat(scheduled_at_utc)
        else:
            dt = scheduled_at_utc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        duration = duration_minutes or self.duration_minutes
        total_slot = duration + self.buffer_minutes

        # Convert to business timezone to verify working hours
        local_dt = dt.astimezone(self.tz)
        slot_start_mins = local_dt.hour * 60 + local_dt.minute
        slot_end_mins = slot_start_mins + duration

        work_start_mins = self.start_hour * 60 + self.start_minute
        work_end_mins = self.end_hour * 60 + self.end_minute

        if slot_start_mins < work_start_mins or slot_end_mins > work_end_mins:
            log.info("slot %s outside working hours (%s-%s)", local_dt, work_start_mins, work_end_mins)
            return False

        if not self.db:
            return True

        # Check DB for overlaps with active confirmed consultations
        # An overlap occurs if existing_start < new_end and existing_end > new_start
        slot_start_iso = dt.isoformat()
        slot_end_iso = (dt + timedelta(minutes=total_slot)).isoformat()

        # Query all active confirmed consultations around this day
        day_start = dt.replace(hour=0, minute=0, second=0).isoformat()
        day_end = dt.replace(hour=23, minute=59, second=59).isoformat()

        query = """
            SELECT scheduled_at, duration_minutes FROM consultations
            WHERE status = 'CONFIRMED'
              AND scheduled_at >= ? AND scheduled_at <= ?
        """
        rows = self.db.execute(query, (day_start, day_end)).fetchall()

        new_start = dt
        new_end = dt + timedelta(minutes=total_slot)

        for r in rows:
            exist_start = datetime.fromisoformat(r["scheduled_at"])
            if exist_start.tzinfo is None:
                exist_start = exist_start.replace(tzinfo=timezone.utc)
            else:
                exist_start = exist_start.astimezone(timezone.utc)

            exist_dur = int(r["duration_minutes"] or self.duration_minutes)
            exist_end = exist_start + timedelta(minutes=exist_dur + self.buffer_minutes)

            # Check overlap interval
            if max(new_start, exist_start) < min(new_end, exist_end):
                log.info("conflict detected with existing consultation at %s", exist_start)
                return False

        return True

    def get_available_slots(self, date_str: str) -> list[str]:
        """Returns list of formatted time strings ('HH:MM') available on the specified date ('YYYY-MM-DD')."""
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return []

        step_minutes = self.duration_minutes + self.buffer_minutes
        curr_mins = self.start_hour * 60 + self.start_minute
        end_mins = self.end_hour * 60 + self.end_minute

        available_slots = []

        while curr_mins + self.duration_minutes <= end_mins:
            hour = curr_mins // 60
            minute = curr_mins % 60
            local_dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=self.tz)
            utc_dt = local_dt.astimezone(timezone.utc)

            if self.is_slot_available(utc_dt):
                available_slots.append(f"{hour:02d}:{minute:02d}")

            curr_mins += step_minutes

        return available_slots
