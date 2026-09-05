"""ConsultationScheduler — Book, manage, cancel, and audit consultations.

Ensures:
- Anti race-condition booking & slot validation.
- Audit event trail (consultation_events).
- Multilingual confirmation cards for customers.
- Instant Telegram notifications to owner.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..ids import new_id, utcnow
from ..log import get_logger
from .availability import AvailabilityEngine
from .meeting_links import generate_meeting_link

log = get_logger("consultation.scheduler")


class ConsultationScheduler:
    """Core booking and management engine for consultations."""

    def __init__(self, db, config: dict | None = None):
        self.db = db
        self.config = config or {}
        self.availability = AvailabilityEngine(db, config=self.config)

    def _next_human_code(self) -> str:
        """Generates sequential AC-1001, AC-1002 human booking codes."""
        if not self.db:
            return f"AC-{new_id()[:6].upper()}"
        row = self.db.execute("SELECT COUNT(*) AS c FROM consultations").fetchone()
        count = (row["c"] if row else 0) + 1001
        return f"AC-{count}"

    def book_consultation(
        self,
        customer_name: str,
        customer_phone: str,
        scheduled_at: str | datetime,
        service: str | None = None,
        meeting_type: str = "GOOGLE_MEET",
        source_platform: str = "whatsapp",
        customer_email: str | None = None,
        customer_id: str | None = None,
        notes: str | None = None,
        language: str = "ar",
    ) -> dict:
        """Atomically books a consultation after verifying availability."""
        if isinstance(scheduled_at, str):
            dt_str = scheduled_at
            dt = datetime.fromisoformat(scheduled_at)
        else:
            dt = scheduled_at
            dt_str = dt.isoformat()

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            dt_str = dt.isoformat()

        # 1. Deterministic Availability Check
        if not self.availability.is_slot_available(dt):
            log.warning("attempted booking on unavailable slot: %s", dt_str)
            return {
                "success": False,
                "error": "SLOT_UNAVAILABLE",
                "message": "الموعد المحدد غير متاح أو خارج ساعات العمل. يرجى اختيار موعد آخر.",
            }

        # 2. Prepare Identifiers & Meeting Link
        cid = new_id()
        human_code = self._next_human_code()
        meeting_url = generate_meeting_link(meeting_type, human_code)
        now = utcnow()

        # 3. Insert Consultation
        try:
            self.db.execute(
                """
                INSERT INTO consultations (
                    id, consultation_id, customer_id, customer_name, customer_phone,
                    customer_email, source_platform, meeting_type, service,
                    scheduled_at, timezone, duration_minutes, meeting_url,
                    status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?, ?, ?)
                """,
                (
                    cid,
                    human_code,
                    customer_id,
                    customer_name,
                    customer_phone,
                    customer_email,
                    source_platform,
                    meeting_type.upper(),
                    service or "استشارة برمجية وتقنية عامة",
                    dt_str,
                    self.availability.tz_name,
                    self.availability.duration_minutes,
                    meeting_url,
                    notes,
                    now,
                    now,
                ),
            )

            # 4. Audit Log Events
            self._log_event(cid, "CREATED", {"human_code": human_code, "scheduled_at": dt_str})
            self._log_event(cid, "MEETING_LINK_CREATED", {"meeting_url": meeting_url})
            self._log_event(cid, "CONFIRMED", {"status": "CONFIRMED"})

            self.db.commit()
            log.info("consultation %s (%s) booked successfully", human_code, cid)
        except Exception as exc:
            log.error("failed inserting consultation: %s", exc)
            return {"success": False, "error": "DB_ERROR", "message": str(exc)}

        # 4b. Calendar event (best-effort: booking stands even if the
        # calendar backend is unconfigured or temporarily failing).
        calendar_info: dict = {}
        try:
            from .calendar import CalendarService

            calendar_info = CalendarService(self.db).create_event({
                "id": cid,
                "consultation_id": human_code,
                "customer_email": customer_email,
                "service": service or "استشارة برمجية وتقنية عامة",
                "scheduled_at": dt_str,
                "duration_minutes": self.availability.duration_minutes,
                "meeting_url": meeting_url,
            })
            self._log_event(cid, "CALENDAR_CREATED", {
                "backend": calendar_info.get("backend"),
                "event_id": calendar_info.get("event_id"),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar create failed for %s: %s", human_code, exc)

        # 5. Format Confirmation Card
        confirmation_msg = self.format_customer_confirmation(
            human_code=human_code,
            customer_name=customer_name,
            scheduled_at=dt,
            service=service or "استشارة تقنية",
            meeting_type=meeting_type,
            meeting_url=meeting_url,
            language=language,
        )

        # 6. Notify Owner on Telegram
        self._notify_owner(
            human_code=human_code,
            customer_name=customer_name,
            customer_phone=customer_phone,
            platform=source_platform,
            service=service or "استشارة تقنية",
            scheduled_at=dt,
            meeting_type=meeting_type,
            meeting_url=meeting_url,
        )

        # 7. Confirmation email with calendar invite (best-effort).
        if customer_email:
            try:
                from ..channels.email import send_email

                cal_line = (f"\nAdd to calendar: {calendar_info.get('link')}\n"
                            if calendar_info.get("link") else "")
                send_email(
                    str(customer_email).strip().lower(),
                    f"AmanCode consultation confirmed #{human_code}",
                    f"{confirmation_msg}{cal_line}",
                    ics_content=calendar_info.get("ics"),
                    ics_filename=f"amancode-{human_code}.ics",
                )
                self._log_event(cid, "CONFIRMATION_EMAIL_SENT", {"to": str(customer_email).strip().lower()})
            except Exception as exc:  # noqa: BLE001
                log.warning("confirmation email failed for %s: %s", human_code, exc)

        return {
            "success": True,
            "id": cid,
            "consultation_id": human_code,
            "customer_name": customer_name,
            "scheduled_at": dt_str,
            "meeting_type": meeting_type,
            "meeting_url": meeting_url,
            "confirmation_message": confirmation_msg,
        }

    def cancel_consultation(self, consultation_id: str, reason: str = "") -> dict:
        """Cancels a consultation and records cancellation in audit events."""
        row = self.db.execute(
            "SELECT * FROM consultations WHERE id = ? OR consultation_id = ?",
            (consultation_id, consultation_id),
        ).fetchone()

        if not row:
            return {"success": False, "error": "NOT_FOUND", "message": "لم يتم العثور على موعد بهذا المعرف."}

        if row["status"] == "CANCELLED":
            return {"success": False, "error": "ALREADY_CANCELLED", "message": "الموعد ملغي بالفعل."}

        now = utcnow()
        cid = row["id"]
        human_code = row["consultation_id"]

        self.db.execute(
            "UPDATE consultations SET status = 'CANCELLED', cancelled_at = ?, updated_at = ? WHERE id = ?",
            (now, now, cid),
        )
        self._log_event(cid, "CANCELLED", {"reason": reason, "cancelled_at": now})
        self.db.commit()

        # Best-effort: delete calendar event + notify by email when known.
        try:
            from .calendar import CalendarService

            cal_res = CalendarService(self.db).cancel_event(cid)
            self._log_event(cid, "CALENDAR_CANCELLED", cal_res)
        except Exception as exc:  # noqa: BLE001
            log.warning("calendar cancel failed for %s: %s", human_code, exc)
        customer_email = str(dict(row).get("customer_email") or "")
        if customer_email:
            try:
                from ..channels.email import send_email

                send_email(
                    str(customer_email).strip().lower(),
                    f"AmanCode consultation cancelled #{human_code}",
                    f"Your consultation #{human_code} scheduled at {row['scheduled_at']} "
                    f"has been cancelled. {('Reason: ' + reason) if reason else ''}\n"
                    "Reply to this email to reschedule.",
                )
                self._log_event(cid, "CANCELLATION_EMAIL_SENT", {})
            except Exception as exc:  # noqa: BLE001
                log.warning("cancellation email failed for %s: %s", human_code, exc)

        log.info("consultation %s (%s) cancelled", human_code, cid)
        return {
            "success": True,
            "consultation_id": human_code,
            "customer_name": row["customer_name"],
            "scheduled_at": row["scheduled_at"],
            "message": f"تم إلغاء الموعد {human_code} بنجاح.",
        }

    def list_upcoming(self, limit: int = 20) -> list[dict]:
        """Lists active confirmed consultations ordered by scheduled_at."""
        now = utcnow()
        rows = self.db.execute(
            """
            SELECT * FROM consultations
            WHERE status = 'CONFIRMED' AND scheduled_at >= ?
            ORDER BY scheduled_at ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _log_event(self, consultation_id: str, event_type: str, metadata: dict | None = None) -> None:
        try:
            self.db.execute(
                """
                INSERT INTO consultation_events (event_id, consultation_id, event_type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_id(), consultation_id, event_type, json.dumps(metadata or {}, ensure_ascii=False), utcnow()),
            )
        except Exception as exc:
            log.error("failed logging consultation event: %s", exc)

    def format_customer_confirmation(
        self,
        human_code: str,
        customer_name: str,
        scheduled_at: datetime,
        service: str,
        meeting_type: str,
        meeting_url: str,
        language: str = "ar",
    ) -> str:
        local_dt = scheduled_at.astimezone(self.availability.tz)
        date_str = local_dt.strftime("%Y-%m-%d")
        time_str = local_dt.strftime("%H:%M")

        if language == "en":
            return (
                f"✅ **AmanCode — Consultation Confirmed**\n\n"
                f"👤 Client: {customer_name}\n"
                f"📅 Date: {date_str}\n"
                f"⏰ Time: {time_str} ({self.availability.tz_name})\n"
                f"⏱️ Duration: {self.availability.duration_minutes} Mins\n"
                f"📌 Service: {service}\n"
                f"💻 Meeting Link: {meeting_url}\n\n"
                f"🔖 Booking ID: #{human_code}\n\n"
                f"We look forward to speaking with you!"
            )
        elif language == "id":
            return (
                f"✅ **AmanCode — Konfirmasi Konsultasi**\n\n"
                f"👤 Klien: {customer_name}\n"
                f"📅 Tanggal: {date_str}\n"
                f"⏰ Waktu: {time_str} ({self.availability.tz_name})\n"
                f"⏱️ Durasi: {self.availability.duration_minutes} Menit\n"
                f"📌 Layanan: {service}\n"
                f"💻 Link Pertemuan: {meeting_url}\n\n"
                f"🔖 ID Booking: #{human_code}\n\n"
                f"Kami siap membantu proyek Anda!"
            )
        else:
            return (
                f"✅ **تأكيد موعد استشارة — أمان كود (AmanCode)**\n\n"
                f"👤 العميل: أستاذ {customer_name}\n"
                f"📅 التاريخ: {date_str}\n"
                f"⏰ الوقت: {time_str} (توقيت مكة / مكسار)\n"
                f"⏱️ المدة: {self.availability.duration_minutes} دقيقة\n"
                f"📌 مجال الاستشارة: {service}\n"
                f"💻 رابط الاجتماع المباشر:\n{meeting_url}\n\n"
                f"🔖 رقم الحجز: #{human_code}\n\n"
                f"يسعدنا التحدث معكم ومناقشة متطلبات مشروعكم بدقة 🚀"
            )

    def _notify_owner(
        self,
        human_code: str,
        customer_name: str,
        customer_phone: str,
        platform: str,
        service: str,
        scheduled_at: datetime,
        meeting_type: str,
        meeting_url: str,
    ) -> None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return

        local_dt = scheduled_at.astimezone(self.availability.tz)
        date_str = local_dt.strftime("%Y-%m-%d")
        time_str = local_dt.strftime("%H:%M")

        text = (
            f"🗓️ **حجز استشارة واجتماع جديد!**\n\n"
            f"👤 العميل: {customer_name}\n"
            f"📱 الهاتف: `{customer_phone}`\n"
            f"🌐 المنصة: {platform}\n\n"
            f"📌 الخدمة: {service}\n"
            f"📅 التاريخ: {date_str}\n"
            f"⏰ الوقت: {time_str} ({self.availability.tz_name})\n"
            f"⏱️ المدة: {self.availability.duration_minutes} دقيقة\n"
            f"📹 النوع: {meeting_type}\n\n"
            f"🔗 رابط الاجتماع:\n{meeting_url}\n\n"
            f"🔖 معرف الحجز: #{human_code}"
        )

        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            self._log_event(human_code, "OWNER_NOTIFIED", {"chat_id": chat_id})
        except Exception as exc:
            log.warning("failed sending telegram consultation alert: %s", exc)
