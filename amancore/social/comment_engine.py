"""SocialCommentEngine — intelligent auto-comment, like, DM, and moderation.

Features:
- Human-like, warm consultative Arabic responses representing AmanCode.
- Context-aware intent classification (Pricing, Service Inquiry, Praise, Spam/Offensive).
- Auto-Like, Public Reply, and Private DM generation.
- Intelligent Moderation (Automatic Hiding/Deletion of offensive comments + Telegram owner alert).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..ids import new_id, utcnow
from ..log import get_logger

log = get_logger("social.comment_engine")


COMMENT_SYSTEM_PROMPT = """أنت مستشار علاقات العملاء والتواصل الرقمي في شركة أمان كود (AmanCode).
مهمتك تحليل والرد على تعليقات المتابعين في منصات التواصل الاجتماعي (فيسبوك، انستغرام، تيك توك) بأسلوب بشري دافئ، ذكي، وراقٍ.

سياق خدمات أمان كود (AmanCode):
- تطوير وبرمجة المواقع والمتاجر الإلكترونية والتطبيقات الحديثة.
- بناء أنظمة الـ ERP المصغرة وأتمتة العمليات وربط الأنظمة.
- وكلاء وأنظمة الذكاء الاصطناعي (AI Agents) والشات بوت المخصص للأعمال.
- تصميم الهوية البصرية المتكاملة والشعارات (Logos) الاحترافية حسب الطلب.

قواعد الرد البشري التلقائي:
1. تحدث كإنسان حقيقي محترف ودود (مثل مستشار العلاقات العامة في الشركة)، وتجنب العبارات الروبوتية الجافة أو التكرار الممل.
2. إذا كان التعليق يسأل عن السعر أو التفاصيل:
   - في الرد العام (public_reply): رحب بالمعلق باسمه إن وجد بلطف، وأخبره باختصار أننا أرسلنا له التفاصيل الكاملة في الخاص (DM) لخدمته بشكل أفضل.
   - في رسالة الخاص (dm_message): اكتب رسالة ترحيبية مهذبة تقدم تفاصيل الخدمة وتدعوه لمناقشة متطلبات مشروعه.
3. إذا كان التعليق إشادة أو تشجيعاً:
   - اشكره بلطف واكتب دعاءً أو أمنية طيبة ("شكراً لذوقك وكلماتك الطيبة أستاذ... نسعد دائماً بخدمتكم ✨").
4. إذا كان التعليق يحتوي على إساءة، ألفاظ نابية، روابط احتيالية، سبام، أو دعاية لمنافسين:
   - صنف التعليق كـ SPAM_OR_OFFENSIVE وحدد الإجراء المناسب (HIDE أو DELETE).

أخرج النتيجة ككائن JSON صالح فقط بدون أي نصوص إضافية، بالحقول التالية:
{
  "intent": "INQUIRY_PRICING" | "INQUIRY_SERVICE" | "PRAISE" | "GENERAL_QUESTION" | "SPAM_OR_OFFENSIVE",
  "sentiment": "positive" | "neutral" | "negative" | "toxic",
  "is_offensive": false | true,
  "should_like": true | false,
  "public_reply": "نص الرد العام على التعليق باللغة العربية بأسلوب راقٍ",
  "dm_message": "نص الرسالة الخاصة للعميل في DM أو null إذا لم يكن هناك حاجة لرسالة خاصة",
  "action": "REPLY_AND_DM" | "REPLY_ONLY" | "LIKE_ONLY" | "HIDE" | "DELETE" | "FLAG_REVIEW",
  "moderation_reason": "سبب الحظر أو الإخفاء إن وجد أو null"
}
"""


class SocialCommentEngine:
    """Intelligent comment analyzer, replier, and safety moderator."""

    def __init__(self, db=None):
        self.db = db

    def analyze_comment(
        self,
        channel: str,
        comment_text: str,
        commenter_name: str | None = None,
        post_caption: str | None = None,
    ) -> dict:
        comment_text = (comment_text or "").strip()
        commenter_name = (commenter_name or "المتابع الكريم").strip()
        post_caption = (post_caption or "منشور أمان كود التقني").strip()

        # Quick local rule-based safety check for toxic words
        offensive_patterns = [
            r"(نصاب|احتيال|حرامي|سرقة|كذاب|شتيمة|fuck|shit|scam|spam|bit\.ly|t\.me/)",
        ]
        is_hard_toxic = any(re.search(pat, comment_text, re.I) for pat in offensive_patterns)

        user_input = f"""منصة التواصل: {channel}
اسم المعلق: {commenter_name}
سياق المنشور: {post_caption[:200]}
نص التعليق: {comment_text}
"""
        # Call Gemini or fallback
        raw_json = self._call_ai(user_input)
        result = self._parse_json(raw_json)

        if not result or not isinstance(result, dict):
            # Safe heuristic fallback
            result = self._heuristic_fallback(comment_text, commenter_name, is_hard_toxic)

        if is_hard_toxic:
            result["is_offensive"] = True
            result["action"] = "HIDE"
            result["should_like"] = False
            result["public_reply"] = ""
            result["dm_message"] = None

        return result

    def _call_ai(self, prompt_text: str) -> str:
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if deepseek_key:
            try:
                from ..voice.pipeline import continue_with_deepseek
                system_prompt = COMMENT_SYSTEM_PROMPT + "\n\nيجب أن يكون ردك بصيغة JSON فقط متوافقاً مع الحقول المطلوبة وبدون أي كود ماركداون إضافي."
                return continue_with_deepseek(prompt_text, system=system_prompt)
            except Exception as exc:
                log.warning("comment engine deepseek call failed: %s", exc)

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return ""

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            model_id = os.environ.get("AMANCODE_MODEL_DEFAULT", "gemini-2.5-flash")
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=COMMENT_SYSTEM_PROMPT + "\n\n" + prompt_text)
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            return (response.text or "").strip()
        except Exception as exc:
            log.warning("comment engine gemini call failed: %s", exc)
            return ""

    def _parse_json(self, text: str) -> dict | None:
        if not text:
            return None
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        try:
            return json.loads(clean.strip())
        except Exception:
            return None

    def _heuristic_fallback(self, text: str, name: str, is_toxic: bool) -> dict:
        if is_toxic:
            return {
                "intent": "SPAM_OR_OFFENSIVE",
                "sentiment": "toxic",
                "is_offensive": True,
                "should_like": False,
                "public_reply": "",
                "dm_message": None,
                "action": "HIDE",
                "moderation_reason": "ألفاظ غير لائقة أو روابط مشبوهة",
            }

        text_lower = text.lower()
        if any(w in text_lower for w in ("سعر", "بكم", "تكلفة", "تفاصيل", "عرض", "كم")):
            return {
                "intent": "INQUIRY_PRICING",
                "sentiment": "positive",
                "is_offensive": False,
                "should_like": True,
                "public_reply": f"أهلاً بك أستاذ {name}! يسعدنا اهتمامك 💡 تم إرسال التفاصيل والأسعار لك في الخاص (DM) لخدمتك بشكل أفضل 🚀",
                "dm_message": f"مرحباً بك أستاذ {name}! بخصوص استفسارك عن خدمات وحلول أمان كود (AmanCode)، يسعدنا تقديم استشارة مخصصة لمشروعك. كيف يمكننا مساعدتك اليوم؟",
                "action": "REPLY_AND_DM",
                "moderation_reason": None,
            }
        elif any(w in text_lower for w in ("ما شاء الله", "ممتاز", "رائع", "مبدعين", "بالتوفيق", "شكرا", "جميل")):
            return {
                "intent": "PRAISE",
                "sentiment": "positive",
                "is_offensive": False,
                "should_like": True,
                "public_reply": f"شكراً لذوقك وكلماتك الراقية أستاذ {name} ✨ نسعد دائماً بخدمتكم وتواجدكم معنا 🌟",
                "dm_message": None,
                "action": "REPLY_ONLY",
                "moderation_reason": None,
            }
        else:
            return {
                "intent": "GENERAL_QUESTION",
                "sentiment": "neutral",
                "is_offensive": False,
                "should_like": True,
                "public_reply": f"أهلاً بك أستاذ {name}! نسعد بتواصلك معنا، يسعدنا تزويدك بكافة المعلومات والاستشارات التقنية عبر الرسائل الخاصة أو واتساب 💡",
                "dm_message": f"أهلاً بك أستاذ {name}! فريق أمان كود في خدمتك لأي استفسار حول تطوير الأنظمة والمواقع والهويات البصرية.",
                "action": "REPLY_AND_DM",
                "moderation_reason": None,
            }

    def record_comment(
        self,
        channel: str,
        comment_id: str,
        comment_text: str,
        analysis: dict,
        commenter_name: str | None = None,
        post_id: str | None = None,
        post_caption: str | None = None,
    ) -> bool:
        if not self.db:
            return False
        try:
            now = utcnow()
            self.db.execute(
                """
                INSERT OR REPLACE INTO social_comments (
                    comment_id, channel, post_id, post_caption,
                    commenter_id, commenter_name, comment_text,
                    intent, sentiment, public_reply, dm_message,
                    action_taken, is_offensive, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    comment_id,
                    channel,
                    post_id,
                    post_caption,
                    None,
                    commenter_name,
                    comment_text,
                    analysis.get("intent"),
                    analysis.get("sentiment"),
                    analysis.get("public_reply"),
                    analysis.get("dm_message"),
                    analysis.get("action"),
                    1 if analysis.get("is_offensive") else 0,
                    now,
                    now,
                ),
            )
            self.db.commit()
            return True
        except Exception as exc:
            log.error("failed recording social comment: %s", exc)
            return False
