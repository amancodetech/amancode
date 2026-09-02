"""ContentAutopilotEngine — Autonomous Daily Content Generator & High-End Branded Banner Engine.

Adheres strictly to the AmanCode Master Brand Identity:
- Palette: Graphite Black (#17191C), Warm Ivory (#F3F1EA), Deep Emerald (#236B57)
- Anti-AI: Clean, engineered geometry, architectural framing, zero neon glow / cyberpunk
- Authoritative Logo: Embeds official assets/LOGO.png with crisp alpha blending
- Cross-Channel Broadcast: Facebook + Instagram + TikTok + WhatsApp Status + Stories
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..brand.tokens import (
    BRAND_NAME_AR,
    BRAND_NAME_EN,
    COLOR_ACCENT,
    COLOR_DARK_BG,
    COLOR_DARK_BORDER,
    COLOR_DARK_SURFACE,
    COLOR_DARK_TEXT_MUTED,
    COLOR_DARK_TEXT_PRIMARY,
    COLOR_SECONDARY,
    LOGO_PATH,
)
from ..ids import new_id, utcnow
from ..log import get_logger

log = get_logger("content.autopilot")

# 7-Day Thematic Content Matrix
WEEKLY_MATRIX = {
    0: {
        "key": "ai_agents",
        "category_name": "الذكاء الاصطناعي والأتمتة",
        "badge": "ذكاء اصطناعي وأتمتة",
        "topic": "وكلاء الذكاء الاصطناعي (AI Agents)، الشات بوت الذكي، وأتمتة العمليات اليومية لزيادة المبيعات وخفض التكاليف التشغيلية",
        "accent": COLOR_ACCENT,
    },
    1: {
        "key": "mini_erp",
        "category_name": "الأنظمة السحابية وإدارة الأعمال",
        "badge": "أنظمة سحابية وERP",
        "topic": "بناء أنظمة الـ ERP المصغرة، إدارة المخزون، ونقاط البيع المخصصة ولوحات التحكم السحابية المتقدمة",
        "accent": COLOR_ACCENT,
    },
    2: {
        "key": "tech_tips",
        "category_name": "الأمان السيبراني واستشارات التقنية",
        "badge": "أمان وحماية الأنظمة",
        "topic": "حماية البيانات، أمان البنية التحتية السحابية، تسريع أداء المتاجر، وأفضل الممارسات الهندسية",
        "accent": COLOR_ACCENT,
    },
    3: {
        "key": "branding_visual_identity",
        "category_name": "الهوية البصرية والأنظمة التجارية",
        "badge": "هندسة الهوية البصرية",
        "topic": "بناء الهوية البصرية المتكاملة للشركات التقنية، تصميم العلامات التجارية، ودليل الاستخدام الهندسي الموحد",
        "accent": COLOR_ACCENT,
    },
    4: {
        "key": "tech_innovation",
        "category_name": "الابتكار البرمجي وهندسة الحلول",
        "badge": "ابتكار وهندسة رقمية",
        "topic": "تحويل التحديات البرمجية المعقدة إلى حلول مؤتمتة فائقة السرعة والأداء للشركات الحديثة",
        "accent": COLOR_ACCENT,
    },
    5: {
        "key": "web_apps",
        "category_name": "تطوير المتاجر والتطبيقات السحابية",
        "badge": "متاجر وتطبيقات سحابية",
        "topic": "تطوير المنصات الرقمية والمتاجر الإلكترونية السريعة وتطبيقات الويب الحديثة بأعلى معايير الأمان",
        "accent": COLOR_ACCENT,
    },
    6: {
        "key": "offers_packages",
        "category_name": "حلول أمان كود المتكاملة",
        "badge": "حلول برمجية متكاملة",
        "topic": "باقات AmanCode المتكاملة للشركات (تطوير المنصة + أتمتة الذكاء الاصطناعي + استشارة هندسية مخصصة)",
        "accent": COLOR_ACCENT,
    },
}

AUTOPILOT_PROMPT_TEMPLATE = """
أنت خبير استراتيجية المحتوى والتسويق لشركة «AmanCode — أمان كود» المتخصصة في الحلول البرمجية الذكية، الأمان السيبراني، وتطوير المتاجر والأنظمة السحابية.

المطلوب: توليد فكرة منشور تسويقي تفاعلي عالي القيمة لليوم.
- مجال اليوم: {category_name}
- شارة الموضوع: {badge}
- المحور الأساسي: {topic}

قواعد صياغة المحتوى:
1. النبرة: هندسية، رصينة، واثقة، واستشارية مفيدة (تجنب الابتذال أو ادعاء المستحيل).
2. العنوان: عنوان رئيسي قصير وقوي (من 3 إلى 5 كلمات) صالح ليوضع في البانر التصميمي.
3. العبارة الفرعية: سطر واحد مكمل وملهم (من 5 إلى 8 كلمات).
4. نص المنشور الكامل: فقرة احترافية تشرح الفائدة وتتضمن دعوة للتواصل (Call to Action) وهاشتاجات ذات صلة.

أخرج النتيجة بتنسيق JSON حصراً:
{{
  "title": "عنوان قصير جذاب",
  "subtitle": "عبارة فرعية ملهمة",
  "caption": "نص المنشور الكامل مع الهاشتاجات..."
}}
"""


class ContentAutopilotEngine:
    """Generates and publishes daily autonomous content across all platforms."""

    def __init__(self, db=None):
        self.db = db

    def get_today_theme(self, day_of_week: int | None = None) -> dict:
        if day_of_week is None:
            day_of_week = datetime.now(timezone.utc).weekday()
        return WEEKLY_MATRIX.get(day_of_week, WEEKLY_MATRIX[0])

    def generate_content(self, day_of_week: int | None = None) -> dict:
        theme = self.get_today_theme(day_of_week)
        api_key = os.environ.get("GEMINI_API_KEY")

        if api_key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=api_key)
                prompt = AUTOPILOT_PROMPT_TEMPLATE.format(
                    category_name=theme["category_name"],
                    badge=theme["badge"],
                    topic=theme["topic"],
                )
                model_id = os.environ.get("AMANCODE_MODEL_DEFAULT", "gemini-2.5-flash")
                resp = client.models.generate_content(
                    model=model_id,
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                    config=types.GenerateContentConfig(temperature=0.7, response_mime_type="application/json"),
                )
                raw_json = (resp.text or "").strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json[7:]
                if raw_json.startswith("```"):
                    raw_json = raw_json[3:]
                if raw_json.endswith("```"):
                    raw_json = raw_json[:-3]
                parsed = json.loads(raw_json.strip())
                return {
                    "theme": theme,
                    "title": parsed.get("title", theme["category_name"]),
                    "subtitle": parsed.get("subtitle", "حلول برمجية وهندسية متقدمة"),
                    "caption": parsed.get("caption", f"🚀 أمان كود | {theme['topic']}\n\nتواصل معنا الآن للحصول على استشارتك المجانية 💡 #AmanCode"),
                }
            except Exception as exc:
                log.warning("autopilot gemini generation failed, using template: %s", exc)

        # High-quality fallback template
        return {
            "theme": theme,
            "title": theme["category_name"],
            "subtitle": "تقنية متقدمة مصممة بأعلى معايير الأمان والذكاء",
            "caption": (
                f"🚀 {theme['badge']} | أمان كود (AmanCode)\n\n"
                f"💡 {theme['topic']}\n\n"
                f"✨ نساعدك في بناء وتطوير أنظمتك التقنية بأعلى معايير الأمان والسرعة والكفاءة الهندسية.\n\n"
                f"📲 تواصل معنا الآن لبدء استشارتك الفنية ومناقشة متطلبات مشروعك.\n\n"
                f"#AmanCode #برمجة #ذكاء_اصطناعي #أمان_كود #أنظمة_سحابية #تقنية"
            ),
        }

    def create_banner(self, title: str, subtitle: str, badge: str, accent_hex: str = COLOR_ACCENT, output_path: str | None = None) -> str:
        """Renders an elegant, high-resolution 1080x1080 visual banner aligned with AmanCode's mature brand identity."""
        from PIL import Image, ImageDraw, ImageFont
        import arabic_reshaper
        from bidi.algorithm import get_display

        width, height = 1080, 1080
        # 1. Base Canvas: Graphite Black (#17191C)
        img = Image.new("RGB", (width, height), color=COLOR_DARK_BG)
        draw = ImageDraw.Draw(img)

        # 2. Architectural Structural Card
        card_box = [60, 60, 1020, 1020]
        draw.rounded_rectangle(card_box, radius=20, fill=COLOR_DARK_SURFACE, outline=COLOR_DARK_BORDER, width=2)

        # Subtle Architectural Accent Header Line (Deep Emerald #236B57)
        draw.line([(90, 60), (990, 60)], fill=COLOR_ACCENT, width=4)

        # 3. Fonts Loading
        font_path_bold = "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf"
        font_path_reg = "/usr/share/fonts/truetype/noto/NotoKufiArabic-Regular.ttf"

        if not os.path.exists(font_path_bold):
            font_path_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            font_path_reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        font_brand = ImageFont.truetype(font_path_bold, 30)
        font_badge = ImageFont.truetype(font_path_bold, 24)
        font_title = ImageFont.truetype(font_path_bold, 50)
        font_sub = ImageFont.truetype(font_path_reg, 32)
        font_footer = ImageFont.truetype(font_path_bold, 24)
        font_mono = ImageFont.truetype(font_path_reg, 22)

        def shape_ar(text: str) -> str:
            try:
                reshaped = arabic_reshaper.reshape(text)
                return get_display(reshaped)
            except Exception:
                return text

        # 4. Embed Authoritative AmanCode Logo from assets/
        if LOGO_PATH.exists():
            try:
                logo_img = Image.open(LOGO_PATH).convert("RGBA")
                logo_resized = logo_img.resize((84, 84), Image.Resampling.LANCZOS)
                img.paste(logo_resized, (100, 100), logo_resized)
            except Exception as exc:
                log.warning("failed embedding logo: %s", exc)

        # Header Typography
        draw.text((205, 115), "AmanCode", fill=COLOR_SECONDARY, font=font_brand)
        ar_brand_text = shape_ar("أمان كود")
        draw.text((205, 155), ar_brand_text, fill=COLOR_DARK_TEXT_MUTED, font=font_mono)

        draw.text((820, 125), "ENGINEERED", fill=COLOR_ACCENT, font=font_mono)
        draw.line([(100, 210), (980, 210)], fill=COLOR_DARK_BORDER, width=2)

        # 5. Badge Pill (Deep Emerald Border & Subtle Interior)
        badge_shaped = shape_ar(badge)
        badge_w = draw.textlength(badge_shaped, font=font_badge)
        badge_box = [(width - badge_w) // 2 - 28, 290, (width + badge_w) // 2 + 28, 350]
        draw.rounded_rectangle(badge_box, radius=12, fill="#182A24", outline=COLOR_ACCENT, width=2)
        draw.text(((width - badge_w) // 2, 305), badge_shaped, fill=COLOR_SECONDARY, font=font_badge)

        # 6. Main Headline (Title)
        title_shaped = shape_ar(title)
        title_w = draw.textlength(title_shaped, font=font_title)
        draw.text(((width - title_w) // 2, 450), title_shaped, fill=COLOR_SECONDARY, font=font_title)

        # 7. Subtitle
        sub_shaped = shape_ar(subtitle)
        sub_w = draw.textlength(sub_shaped, font=font_sub)
        draw.text(((width - sub_w) // 2, 545), sub_shaped, fill=COLOR_DARK_TEXT_MUTED, font=font_sub)

        # 8. Subtle Engineering Grid Accent Line
        draw.line([((width // 2) - 80, 650), ((width // 2) + 80, 650)], fill=COLOR_ACCENT, width=3)

        # 9. Clean Footer
        draw.line([(100, 880), (980, 880)], fill=COLOR_DARK_BORDER, width=2)
        footer_text = shape_ar("حلول برمجية آمنة ومؤتمتة للأعمال")
        draw.text((100, 915), footer_text, fill=COLOR_DARK_TEXT_MUTED, font=font_footer)
        draw.text((780, 915), "amancode.tech", fill=COLOR_SECONDARY, font=font_footer)

        if not output_path:
            tmp_dir = Path(tempfile.gettempdir()) / "amancore_autopilot"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(tmp_dir / f"autopilot_{int(datetime.now().timestamp())}.jpg")

        img.save(output_path, "JPEG", quality=95)
        log.info("rendered mature brand autopilot banner: %s", output_path)
        return output_path

    def run_daily_autopilot(self, day_of_week: int | None = None) -> dict:
        """Executes the full pipeline: generation + banner design + broadcast."""
        log.info("running daily content autopilot pipeline...")
        content = self.generate_content(day_of_week)
        theme = content["theme"]

        banner_path = self.create_banner(
            title=content["title"],
            subtitle=content["subtitle"],
            badge=theme["badge"],
            accent_hex=theme.get("accent", COLOR_ACCENT),
        )

        root = Path(__file__).resolve().parents[2]
        meta_post_script = root / "bridge" / "meta-bridge" / "scripts" / "meta-create-post.js"
        meta_story_script = root / "bridge" / "meta-bridge" / "scripts" / "meta-create-story.js"
        tiktok_script = root / "bridge" / "meta-bridge" / "scripts" / "tiktok-create-post.js"

        published_platforms = []
        caption = content["caption"]

        # 1. Meta Post
        if meta_post_script.exists():
            try:
                env = os.environ.copy()
                env["POST_IMAGE"] = banner_path
                env["POST_CAPTION"] = caption
                p = subprocess.run(["node", str(meta_post_script)], env=env, capture_output=True, text=True, timeout=90)
                if p.returncode == 0:
                    published_platforms.extend(["facebook", "instagram"])
            except Exception as exc:
                log.warning("meta post broadcast failed: %s", exc)

        # 2. Meta Story
        if meta_story_script.exists():
            try:
                env = os.environ.copy()
                env["STORY_IMAGE"] = banner_path
                p = subprocess.run(["node", str(meta_story_script)], env=env, capture_output=True, text=True, timeout=90)
                if p.returncode == 0:
                    published_platforms.append("meta_story")
            except Exception as exc:
                log.warning("meta story broadcast failed: %s", exc)

        # 3. TikTok Studio Post
        if tiktok_script.exists():
            try:
                env = os.environ.copy()
                env["TIKTOK_MEDIA"] = banner_path
                env["TIKTOK_TITLE"] = content["title"]
                p = subprocess.run(["node", str(tiktok_script)], env=env, capture_output=True, text=True, timeout=90)
                if p.returncode == 0:
                    published_platforms.append("tiktok")
            except Exception as exc:
                log.warning("tiktok post broadcast failed: %s", exc)

        # 4. WhatsApp Status Broadcast
        bridge_token = os.environ.get("AMANCODE_BRIDGE_TOKEN", "5d4cb44f37189de5759a7d45074e6998ad82f1985f1753ea")
        try:
            import requests

            requests.post(
                "http://127.0.0.1:8765/v1/messages/send",
                headers={"Content-Type": "application/json", "X-Bridge-Token": bridge_token},
                json={
                    "channel": "whatsapp",
                    "to": "status@broadcast",
                    "message": {"type": "image", "image": banner_path, "caption": caption},
                },
                timeout=15,
            )
            published_platforms.append("whatsapp_status")
        except Exception as exc:
            log.warning("whatsapp status broadcast failed: %s", exc)

        return {
            "status": "success",
            "published_at": utcnow(),
            "theme": theme["key"],
            "title": content["title"],
            "banner_path": banner_path,
            "published_platforms": published_platforms,
        }
