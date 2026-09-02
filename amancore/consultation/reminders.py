"""ConsultationReminderService — Idempotent 60m and 15m automated meeting reminders.

Guarantees:
- Strictly idempotent via consultation_events audit trail.
- Multi-channel delivery (WhatsApp / Telegram / Bridge).
- Both customer and owner receive timely reminders.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..log import get_logger

log = get_logger("consultation.reminders")


class ConsultationReminderService:
    """Checks and fires 60-min and 15-min consultation reminders."""

    def __init__(self, db, config: dict | None = None):
        self.db = db
        self.config = config or {}

    def check_and_send_reminders(self) -> dict:
        """Finds due consultations and sends idempotent 60m / 15m reminders."""
        if not self.db:
            return {"sent_60m": 0, "sent_15m": 0}

        now_utc = datetime.now(timezone.utc)
        # Check window up to 75 minutes ahead
        future_cutoff = (now_utc + timedelta(minutes=75)).isoformat()
        past_cutoff = (now_utc - timedelta(minutes=5)).isoformat()

        rows = self.db.execute(
            """
            SELECT * FROM consultations
            WHERE status = 'CONFIRMED'
              AND scheduled_at >= ? AND scheduled_at <= ?
            """,
            (past_cutoff, future_cutoff),
        ).fetchall()

        sent_60m = 0
        sent_15m = 0

        for r in rows:
            cid = r["id"]
            human_code = r["consultation_id"]
            scheduled_at = datetime.fromisoformat(r["scheduled_at"])
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            else:
                scheduled_at = scheduled_at.astimezone(timezone.utc)

            diff_mins = (scheduled_at - now_utc).total_seconds() / 60.0

            # 1. 60-Minute Reminder (between 45 and 65 mins remaining)
            if 45 <= diff_mins <= 65:
                if not self._has_event(cid, "REMINDER_60M_SENT"):
                    self._send_reminder(r, mins=60)
                    self._log_event(cid, "REMINDER_60M_SENT", {"mins_before": 60, "diff_mins": round(diff_mins, 1)})
                    sent_60m += 1

            # 2. 15-Minute Reminder (between 5 and 20 mins remaining)
            if 5 <= diff_mins <= 20:
                if not self._has_event(cid, "REMINDER_15M_SENT"):
                    self._send_reminder(r, mins=15)
                    self._log_event(cid, "REMINDER_15M_SENT", {"mins_before": 15, "diff_mins": round(diff_mins, 1)})
                    sent_15m += 1

        self.db.commit()
        log.info("reminder check completed (sent_60m=%d, sent_15m=%d)", sent_60m, sent_15m)
        return {"sent_60m": sent_60m, "sent_15m": sent_15m}

    def _has_event(self, consultation_id: str, event_type: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM consultation_events WHERE consultation_id = ? AND event_type = ? LIMIT 1",
            (consultation_id, event_type),
        ).fetchone()
        return bool(row)

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
            log.error("failed logging reminder event: %s", exc)

    def _send_reminder(self, consultation_row: dict | sqlite3.Row, mins: int) -> None:
        data = dict(consultation_row)
        name = data.get("customer_name") or "الكريم"
        phone = data.get("customer_phone")
        service = data.get("service") or "الاستشارة"
        meeting_url = data.get("meeting_url")
        human_code = data.get("consultation_id")

        # Customer message
        if mins == 60:
            cust_text = (
                f"⏰ **تذكير بموعد الاستشارة — أمان كود (AmanCode)**\n\n"
                f"أهلاً بك أستاذ {name}! نود تذكيرك بأن موعد استشارتك حول «{service}» سيبدأ بعد **ساعة واحدة** 💡\n\n"
                f"🔗 رابط الاجتماع المباشر:\n{meeting_url}\n\n"
                f"رقم الحجز: #{human_code}"
            )
        else:
            cust_text = (
                f"🚀 **موعد الاستشارة سيبدأ بعد 15 دقيقة!**\n\n"
                f"أهلاً بك أستاذ {name}! فريقنا الهندسي جاهز لاستقبالك في غرفة الاجتماع:\n"
                f"🔗 {meeting_url}\n\n"
                f"نتشرف بالحديث معك ✨"
            )

        # Send via WhatsApp Bridge if phone exists
        token = os.environ.get("AMANCODE_BRIDGE_TOKEN", "5d4cb44f37189de5759a7d45074e6998ad82f1985f1753ea")
        if phone and str(phone).replace("+", "").isdigit():
            try:
                import requests

                requests.post(
                    "http://127.0.0.1:8765/v1/messages/send",
                    headers={"Content-Type": "application/json", "X-Bridge-Token": token},
                    json={
                        "channel": "whatsapp",
                        "to": str(phone).replace("+", ""),
                        "message": {"type": "text", "text": cust_text},
                    },
                    timeout=10,
                )
            except Exception as exc:
                log.warning("failed sending customer reminder via bridge: %s", exc)

        # Notify Owner on Telegram
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if tg_token and chat_id:
            owner_text = (
                f"🔔 **تذكير موعد استشارة بعد {mins} دقيقة!**\n\n"
                f"👤 العميل: {name} (`{phone}`)\n"
                f"📌 الخدمة: {service}\n"
                f"🔗 الرابط: {meeting_url}\n"
                f"🔖 الحجز: #{human_code}"
            )
            try:
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                data = json.dumps({"chat_id": chat_id, "text": owner_text, "disable_web_page_preview": True}).encode()
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
            except Exception as exc:
                log.warning("failed sending owner reminder: %s", exc)
