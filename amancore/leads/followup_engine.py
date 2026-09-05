"""Honest & Smart Lead Follow-Up Engine.

Provides genuine, respectful, and high-value consultative follow-ups grounded strictly
in AmanCode's real services without making up false claims or fictitious projects.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..ids import new_id, utcnow
from ..log import get_logger

log = get_logger("leads.followup")

HONEST_TEMPLATES = {
    "website_ecommerce": [
        "مرحباً بك أستاذ {name}! أردنا في أمان كود الاطمئنان عما إذا كان لديك أي استفسار إضافي حول المتطلبات الفنية أو نطاق العمل لموقعك/متجرك الإلكتروني. فريقنا الهندسي جاهز لتقديم أي توضيحات تقنية تحتاجها 💡",
        "أهلاً بك أستاذ {name}! في أمان كود نحرص على تقديم حلول برمجية مرنة تناسب مراحل نمو مشروعك وميزانيتك. هل تود مناقشة خطة تنفيذية مخصصة تناسب متطلباتك؟ 🚀",
    ],
    "branding_logo": [
        "مرحباً بك أستاذ {name}! بخصوص تصميم الهوية البصرية وشعار مشروعك، يسعدنا في أمان كود مناقشة التفاصيل والأسلوب الفني الذي تفضله لعلامتك التجارية في أي وقت ✨",
        "أهلاً بك أستاذ {name}! إذا كان لديك أي سؤال حول باقات الهوية البصرية وملفات التصميم التي نسلمها في أمان كود، نحن في خدمتك دائماً 🎨",
    ],
    "ai_agent_automation": [
        "مرحباً بك أستاذ {name}! بخصوص أنظمة الذكاء الاصطناعي والأتمتة لعملياتك، يسعدنا في أمان كود ترتيب استشارة فنية لمساعدتك في تحديد المهام القابلة للأتمتة لرفع كفاءة أعمالك 🤖",
    ],
    "erp_systems": [
        "أهلاً بك أستاذ {name}! نود الاطمئنان عما إذا كنت بحاجة لأي استفسار حول تخصيص نظام الـ ERP ولوحات التحكم لتلائم طبيعة نشاطك التجاري بدقة مع أمان كود 📊",
    ],
    "general": [
        "مرحباً بك أستاذ {name}! نتمنى أن تكون بأفضل حال. يسعدنا في أمان كود دائماً الإجابة على أي تساؤل تقني يخص مشروعك أو التنسيق لمكالمة استشارية سريعة لمناقشة أفكارك 💡",
        "أهلاً بك أستاذ {name}! فريق أمان كود التقني في خدمتك دائماً لأي استفسار أو استشارة حول تطوير أنظمتك الرقمية 🌟",
    ],
}


class HonestLeadFollowupEngine:
    """Manages truthful and consultative follow-ups for dormant leads."""

    def __init__(self, db):
        self.db = db

    def get_pending_followups(self, min_hours: int = 24, max_hours: int = 120) -> list[dict]:
        """Finds leads that had contact but became dormant without opting out."""
        if not self.db:
            return []
        now = datetime.now(timezone.utc)
        min_cutoff = (now - timedelta(hours=min_hours)).isoformat()
        max_cutoff = (now - timedelta(hours=max_hours)).isoformat()

        # Query leads with last_contact_at within window and no active rejection
        query = """
            SELECT l.lead_id, l.name, l.service_interest, l.preferred_channel,
                   l.contact_whatsapp, l.last_contact_at, l.next_followup_at
            FROM leads l
            WHERE l.opt_out = 0
              AND l.last_contact_at IS NOT NULL
              AND l.last_contact_at <= ?
              AND l.last_contact_at >= ?
              AND (l.next_followup_at IS NULL OR l.next_followup_at <= ?)
            ORDER BY l.last_contact_at DESC
            LIMIT 20
        """
        rows = self.db.execute(query, (min_cutoff, max_cutoff, now.isoformat())).fetchall()
        return [dict(r) for r in rows]

    def generate_message(self, lead: dict) -> str:
        """Generates a strictly truthful, polite, and consultative message."""
        name = (lead.get("name") or "الكريم").strip()
        interest = (lead.get("service_interest") or "").lower()

        cat = "general"
        if any(w in interest for w in ("موقع", "متجر", "تطبيق", "web", "store", "app")):
            cat = "website_ecommerce"
        elif any(w in interest for w in ("هوية", "لوجو", "شعار", "تصميم", "brand", "logo")):
            cat = "branding_logo"
        elif any(w in interest for w in ("ذكاء", "شات", "بوت", "أتمتة", "ai", "bot")):
            cat = "ai_agent_automation"
        elif any(w in interest for w in ("erp", "نظام", "مخزون", "محاسب")):
            cat = "erp_systems"

        options = HONEST_TEMPLATES.get(cat, HONEST_TEMPLATES["general"])
        template = options[0]
        return template.format(name=name)

    def execute_followup(self, lead_id: str) -> dict:
        """Enqueues an honest follow-up and advances next_followup_at by 7 days to prevent spam."""
        lead = self.db.execute("SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
        if not lead:
            return {"success": False, "error": "Lead not found"}

        lead_dict = dict(lead)
        if lead_dict.get("opt_out"):
            return {"success": False, "error": "Lead opted out"}

        msg_text = self.generate_message(lead_dict)
        phone = lead_dict.get("contact_whatsapp") or lead_dict.get("lead_id")

        now = datetime.now(timezone.utc)
        next_followup = (now + timedelta(days=7)).isoformat()

        # Update lead to prevent multiple follow-ups
        self.db.execute(
            "UPDATE leads SET next_followup_at=?, updated_at=? WHERE lead_id=?",
            (next_followup, now.isoformat(), lead_id),
        )
        self.db.commit()

        # Send via Bridge if WhatsApp available
        sent = False
        token = os.environ.get("AMANCODE_BRIDGE_TOKEN", "5d4cb44f37189de5759a7d45074e6998ad82f1985f1753ea")
        if phone and phone.isdigit():
            try:
                import requests

                resp = requests.post(
                    "http://127.0.0.1:8765/v1/messages/send",
                    headers={"Content-Type": "application/json", "X-Bridge-Token": token},
                    json={
                        "channel": "whatsapp",
                        "to": phone,
                        "message": {"type": "text", "text": msg_text},
                    },
                    timeout=10,
                )
                sent = (resp.status_code == 200)
            except Exception as exc:
                log.warning("followup bridge send failed: %s", exc)

        if sent and phone:
            try:
                self.db.execute(
                    """
                    INSERT INTO channel_messages (
                        channel, direction, external_user_id, lead_id,
                        external_message_id, body, status, created_at
                    ) VALUES ('whatsapp', 'out', ?, ?, ?, ?, 'sent', ?)
                    """,
                    (phone, lead_id, f"followup-{new_id()[:8]}", msg_text, utcnow())
                )
                self.db.commit()
            except Exception as exc:
                log.warning("failed to record followup in channel_messages: %s", exc)

        log.info("executed honest follow-up for lead %s (sent=%s)", lead_id, sent)
        return {
            "success": True,
            "lead_id": lead_id,
            "lead_name": lead_dict.get("name"),
            "message": msg_text,
            "sent_via_bridge": sent,
        }
