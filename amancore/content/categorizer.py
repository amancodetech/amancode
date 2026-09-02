"""AmanCode Smart Content Categorizer & Tagging System.

Automatically categorizes posts, stories, and customer requests into structured
business taxonomy, assigning Instagram Story Highlights, hashtags, and visual badges.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List

TAXONOMY = {
    "branding_and_design": {
        "name_ar": "الهوية البصرية وتصميم الشعارات",
        "icon": "🎨",
        "highlight_title": "هوية وشعارات",
        "keywords": [
            ("هوية بصرية", 15), ("لوقو", 12), ("لوجو", 12), ("شعار", 10), ("تصميم شعار", 15),
            ("براند", 10), ("براندنج", 10), ("هوية تجارية", 15), ("شعار مخصص", 15),
            ("ui/ux", 10), ("ألوان وهوية", 12), ("فكتور", 8), ("تصميم جرافيك", 10)
        ],
        "hashtags": ["#هوية_بصرية", "#تصميم_شعارات", "#لوجو", "#Branding", "#GraphicDesign", "#AmanCode"]
    },
    "ai_agents": {
        "name_ar": "ذكاء اصطناعي وأتمتة",
        "icon": "🤖",
        "highlight_title": "ذكاء اصطناعي",
        "keywords": [
            ("ذكاء اصطناعي", 15), ("وكيل ذكي", 15), ("بوت", 10), ("بوتات", 10),
            ("أتمتة", 12), ("محادثة آلية", 12), ("chatgpt", 10), ("gemini", 10),
            ("ai", 8), ("automation", 10), ("شات بوت", 12), ("رد آلي", 12)
        ],
        "hashtags": ["#ذكاء_اصطناعي", "#أتمتة_الأعمال", "#AIAgents", "#Chatbot", "#AmanCode"]
    },
    "web_and_apps": {
        "name_ar": "تطوير وبرمجة المواقع والتطبيقات",
        "icon": "💻",
        "highlight_title": "برمجة ومواقع",
        "keywords": [
            ("متجر إلكتروني", 15), ("موقع إلكتروني", 15), ("متاجر إلكترونية", 15),
            ("تطبيقات", 12), ("تطبيق", 10), ("برمجة", 10), ("تطوير مواقع", 15),
            ("سيرفر", 8), ("سحابية", 8), ("api", 8), ("web development", 10)
        ],
        "hashtags": ["#تطوير_مواقع", "#برمجة_تطبيقات", "#متاجر_إلكترونية", "#WebDev", "#AmanCode"]
    },
    "offers_and_pricing": {
        "name_ar": "العروض والباقات الخاصة",
        "icon": "🎁",
        "highlight_title": "عروض وباقات",
        "keywords": [
            ("خصم", 12), ("عروض", 12), ("عرض خاص", 15), ("تخفيض", 12),
            ("باقة", 10), ("باقات", 10), ("سعر خاص", 12), ("مجاناً", 10),
            ("وفر", 8), ("لفترة محدودة", 12), ("offer", 10), ("discount", 10)
        ],
        "hashtags": ["#عروض_خاصة", "#تخفيضات", "#باقات_رقمية", "#Offers", "#AmanCode"]
    },
    "tips_and_tech": {
        "name_ar": "شروحات ومعلومات تقنية",
        "icon": "📚",
        "highlight_title": "شروحات تقنية",
        "keywords": [
            ("نصائح", 12), ("نصيحة", 10), ("شرح", 10), ("شروحات", 12),
            ("كيفية", 10), ("طريقة", 8), ("أمن المعلومات", 12), ("حماية", 10),
            ("أسرار", 8), ("معلومة تقنية", 12), ("tech tips", 10)
        ],
        "hashtags": ["#نصائح_تقنية", "#شروحات", "#معلومات_تقنية", "#TechTips", "#AmanCode"]
    },
    "testimonials_and_success": {
        "name_ar": "آراء العملاء ومشاريعنا",
        "icon": "⭐",
        "highlight_title": "آراء وتجارب",
        "keywords": [
            ("آراء", 12), ("رأي عميل", 15), ("تقييم", 10), ("تجارب عملائنا", 15),
            ("قصة نجاح", 15), ("مشروع جديد", 12), ("أعمالنا", 10), ("portfolio", 10)
        ],
        "hashtags": ["#آراء_العملاء", "#مشاريع_أمان_كود", "#قصص_نجاح", "#Portfolio", "#AmanCode"]
    },
    "consulting_and_solutions": {
        "name_ar": "استشارات وحلول الأعمال",
        "icon": "💡",
        "highlight_title": "استشارات وحلول",
        "keywords": [
            ("استشارة تقنية", 15), ("استشارات", 12), ("تحول رقمي", 15),
            ("بنية تحتية", 10), ("حلول مخصصة", 12), ("تكامل الأنظمة", 12)
        ],
        "hashtags": ["#استشارات_تقنية", "#حلول_أعمال", "#تحول_رقمي", "#TechSolutions", "#AmanCode"]
    },
    "general_services": {
        "name_ar": "خدمات أمان كود العامة",
        "icon": "🚀",
        "highlight_title": "خدماتنا",
        "keywords": [
            ("خدماتنا", 10), ("أمان كود", 8), ("amancode", 8), ("شركة أمان", 8)
        ],
        "hashtags": ["#أمان_كود", "#خدمات_رقمية", "#AmanCode", "#DigitalServices"]
    }
}


def classify_content(text: str) -> Dict[str, Any]:
    """Classify text into a taxonomy category with weighted matching."""
    text_clean = (text or "").lower()

    scores: Dict[str, int] = {cat_id: 0 for cat_id in TAXONOMY}
    for cat_id, cat_info in TAXONOMY.items():
        for kw, weight in cat_info["keywords"]:
            if kw in text_clean:
                scores[cat_id] += weight

    best_cat = max(scores, key=scores.get) if any(scores.values()) and max(scores.values()) > 0 else "general_services"
    cat_data = TAXONOMY[best_cat]

    return {
        "category_id": best_cat,
        "name_ar": cat_data["name_ar"],
        "icon": cat_data["icon"],
        "highlight_title": cat_data["highlight_title"],
        "hashtags": cat_data["hashtags"],
        "badge": f"{cat_data['icon']} {cat_data['name_ar']}",
        "score": scores[best_cat]
    }
