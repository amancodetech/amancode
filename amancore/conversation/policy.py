"""ConversationPolicy — the ONLY source of conversation-behavior direction.

Strategy (weights, thresholds, phrasing hints) lives here — loaded from
``configs/conversation_policy.yaml`` with hard-coded defaults so a missing
or partial file can never break startup. Knowledge (services, industries,
claims) is NOT here: it comes from the Business Brain at plan time.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "value_first": True,
    "max_questions_per_reply": 1,
    "budget_weight_outside_commercial": 0,
    "service_categories": {
        "website": {
            "keywords": ["موقع", "موقع إلكتروني", "صفحة", "website", "web site", "site", "situs", "laman"],
            "brain_service_id": "business_website_system",
        },
        "ecommerce": {
            "keywords": ["متجر", "متاجر", "تجارة إلكترونية", "e-commerce", "ecommerce", "online store", "toko online", "toko"],
            "brain_service_id": "ecommerce_store",
        },
        "mobile": {
            "keywords": ["تطبيق", "تطبيقات", "جوال", "app", "mobile app", "android", "ios", "aplikasi"],
            "brain_service_id": "mobile_app",
        },
        "business_system": {
            "keywords": ["erp", "نظام", "نظام إدارة", "محاسبة", "مخزون", "crm", "إدارة موارد", "sistem", "inventory"],
            "brain_service_id": "business_system_mini_erp",
        },
        "automation": {
            "keywords": ["أتمتة", "اتمتة", "ذكاء اصطناعي", "بوت", "automation", "ai", "chatbot", "bot", "otomatisasi"],
            "brain_service_id": "ai_automation_suite",
        },
    },
    "industry_aliases": {
        "association_ngo": ["جمعية", "جمعيات", "خيرية", "تعاون", "ngo", "association", "charity", "foundation", "yayasan"],
        "restaurant": ["مطعم", "مطاعم", "كافيه", "مقهى", "restaurant", "cafe", "coffee shop", "restoran"],
        "real_estate": ["عقار", "عقارات", "عقاري", "real estate", "realty", "property", "properti"],
        "ecommerce": ["متجر", "تجارة إلكترونية", "e-commerce", "ecommerce", "online store", "toko online"],
        "generic_business": [],
    },
    # Question impact weights per service category (design §7.2).
    # A question is asked only about the highest-weight MISSING field.
    "question_weights": {
        "website": {"key_features": 9, "integrations": 8, "languages": 7, "timeline": 5, "authority": 4, "scale": 4},
        "ecommerce": {"key_features": 8, "scale": 9, "integrations": 8, "languages": 6, "timeline": 6, "authority": 4},
        "mobile": {"key_features": 8, "integrations": 7, "scale": 6, "languages": 4, "timeline": 6, "authority": 4},
        "business_system": {"key_features": 10, "scale": 9, "integrations": 9, "languages": 5, "timeline": 6, "authority": 5},
        "automation": {"key_features": 9, "integrations": 7, "scale": 6, "languages": 3, "timeline": 5, "authority": 4},
        "_default": {"key_features": 9, "integrations": 6, "scale": 5, "languages": 5, "timeline": 5, "authority": 4},
    },
    # Weights ADDED on top when the conversation mode is COMMERCIAL.
    "commercial_boost": {"budget_band": 9, "timeline": 8, "authority": 7},
    # fact keys whose presence satisfies a question field.
    "field_satisfied_by": {
        "key_features": ["scope"],
        "scale": ["users"],
        "languages": ["languages"],
        "integrations": ["integrations"],
        "timeline": ["timeline"],
        "authority": ["authority"],
        "budget_band": ["budget"],
    },
    # One natural ask-hint per field per language. The LLM adapts wording;
    # these pin the INTENT of the question, not the exact sentence.
    "question_hints": {
        "key_features": {
            "ar": "ما الجزء الأهم الذي لا يمكن الاستغناء عنه؟",
            "en": "Which part matters most to you?",
            "id": "Bagian mana yang paling penting?",
        },
        "scale": {
            "ar": "كم عدد المستخدمين أو حجم النشاط تقريبًا؟",
            "en": "Roughly how many users or how big is the operation?",
            "id": "Kira-kira berapa jumlah pengguna atau skala usahanya?",
        },
        "languages": {
            "ar": "بأي لغة أو لغات تريد الواجهة؟",
            "en": "Which language(s) should it support?",
            "id": "Bahasa apa saja yang dibutuhkan?",
        },
        "integrations": {
            "ar": "هل يحتاج ربطًا مع أنظمة موجودة (دفع، واتساب، محاسبة)؟",
            "en": "Does it need to connect to existing systems (payments, WhatsApp, accounting)?",
            "id": "Perlu terhubung dengan sistem lain (pembayaran, WhatsApp, akuntansi)?",
        },
        "timeline": {
            "ar": "متى تحب أن يكون جاهزًا؟",
            "en": "When would you like it ready?",
            "id": "Kapan kira-kira dibutuhkan jadi?",
        },
        "authority": {
            "ar": "من يعتمد المشروع نهائيًا من جهتكم؟",
            "en": "Who gives the final approval on your side?",
            "id": "Siapa yang memberi keputusan akhir?",
        },
        "budget_band": {
            "ar": "ما نطاق الميزانية التقريبي الذي وضعتموه؟",
            "en": "What rough budget range have you set aside?",
            "id": "Kira-kira berapa rentang anggarannya?",
        },
    },
    "request_verbs": [
        "أريد", "نريد", "ابغى", " أحتاج", "احتاج", "نبني", "بناء", "تصميم",
        "need", "want", "looking for", "build", "buat", "butuh", "mau", "cari",
    ],
    "commercial_signals": [
        "كم سعر", "كم تكلف", "بكم", "السعر", "التكلفة", "كم تستغرق", "مدة", "المدة",
        "متى", "الميزانية", "ميزانية", "من يقرر", "من يعتمد", "عرض سعر", "دفعة",
        "how long", "how much time", "timeline", "budget", "price", "cost",
        "berapa lama", "harga", "anggaran",
    ],
    "affirmations": [
        "نعم", "تمام", "صحيح", "ممتاز", "موافق", "حلو", "كذا", " تمام ",
        "yes", "ok", "okay", "good", "great", "correct", "ya", "betul", "setuju",
    ],
    # Customer explicitly delegates the design decision to us — the AI must
    # propose a concrete structure instead of asking the customer to design.
    "suggestion_triggers": [
        "لا أدري", "لا ادري", "ما أعرف", "ما اعرف", "اقترح", "أنت تقترح",
        "عليك الاختيار", "suggest", "you decide", "up to you", "as you see fit",
    ],
    # Arabic display labels for natural multi-intent acknowledgments.
    "category_labels": {
        "website": "موقع إلكتروني",
        "ecommerce": "متجر إلكتروني",
        "mobile": "تطبيق جوال",
        "business_system": "نظام أعمال وإدارة",
        "automation": "أتمتة وذكاء اصطناعي",
    },
    # SUGGEST-INTAKE: before proposing when the customer delegates, ask a few
    # easy-choice questions so the recommendation fits. One per message.
    "suggestion_clarifiers": {
        "_default": [
            {"id": "audience", "fact": "users",
             "q": "من الجمهور الأساسي الذي سيزور الموقع؟",
             "options": ["عملاء محليون", "جمهور واسع", "استخدام داخلي"]},
            {"id": "musthave", "fact": "scope",
             "q": "ما الوظيفة الأهم التي لا يمكن الاستغناء عنها؟",
             "options": ["عرض محتوى ومعلومات", "تواصل وطلبات", "حجز أو دفع"]},
        ],
        "association_ngo": [
            {"id": "donation", "fact": "scope",
             "q": "كيف تفضل استقبال التبرعات عبر الموقع؟",
             "options": ["بوابة تبرع إلكترونية", "تحويل أو تواصل مباشر",
                         "الاثنان معاً"]},
            {"id": "languages", "fact": "languages",
             "q": "بأي لغة أو لغات يظهر الموقع؟",
             "options": ["عربي فقط", "عربي وإنجليزي", "لغات متعددة"]},
        ],
        "restaurant": [
            {"id": "ordering", "fact": "scope",
             "q": "ما الأولوية الأولى في الموقع؟",
             "options": ["إظهار المنيو فقط", "طلبات وتوصيل", "حجز طاولات"]},
        ],
        "real_estate": [
            {"id": "listings", "fact": "scope",
             "q": "كيف تريد عرض العقارات؟",
             "options": ["قائمة بسيطة بالتواصل المباشر",
                         "بحث وفلترة كاملة", "مع خريطة وجولات"]},
        ],
        "ecommerce": [
            {"id": "payments", "fact": "integrations",
             "q": "ما وسيلة الدفع الأنسب لعملائك؟",
             "options": ["دفع إلكتروني بوابة", "تحويل بنكي", "الدفع عند الاستلام"]},
        ],
    },
    # Customer insists we just decide — skip remaining clarifiers.
    "suggestion_skip_triggers": [
        "اقترح مباشرة", "قرر أنت", "انت قرر", "أنت قرر", "قرر بنفسك",
        "بدون أسئلة", "بدون اسئلة", "just decide", "skip questions",
    ],
    # Explicit small-website signals → tiered (mini) starting band + hours.
    "small_scope_triggers": [
        "صفحتين", "صفحة واحدة", "ثلاث صفحات", "3 صفحات", "2 صفحات",
        "تعريفي", "تعريفية", "بسيط", "بسيطة", "موقع صغير",
        "landing page", "one page", "mini site",
    ],
}


class ConversationPolicy:
    """Immutable view over the policy document + deterministic detectors."""

    def __init__(self, data: dict | None = None):
        merged = {k: v for k, v in DEFAULTS.items()}
        if data:
            merged.update(data)
        self.data = merged

    @classmethod
    def load(cls, root: Path | str | None = None) -> "ConversationPolicy":
        data = dict(DEFAULTS)
        if root is not None:
            path = Path(root) / "configs" / "conversation_policy.yaml"
            try:
                overrides = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for key, val in overrides.items():
                    if isinstance(val, dict) and isinstance(data.get(key), dict):
                        merged = dict(data[key])
                        merged.update(val)
                        data[key] = merged
                    else:
                        data[key] = val
            except FileNotFoundError:
                pass
            except Exception:  # noqa: BLE001 — config drift must never kill startup
                pass
        return cls(data)

    # ---- detectors -----------------------------------------------------
    def detect_service_category(self, text: str) -> str | None:
        low = f" {text.lower()} "
        for cat, spec in self.data["service_categories"].items():
            for kw in spec["keywords"]:
                if kw.lower() in low:
                    return cat
        return None

    def detect_industry(self, text: str) -> str | None:
        """Detect industry from the policy's base alias map.

        The Business Brain is the authoritative source of industry names and
        aliases. The planner merges the Brain's ``industry_profiles`` aliases
        into this base map at plan time and calls
        :meth:`detect_industry_with` so no second taxonomy lives here — this
        method is only a mechanism + minimal default set.
        """
        return self.detect_industry_with(text, self.data.get("industry_aliases", {}))

    def detect_industry_with(self, text: str, aliases: dict) -> str | None:
        """Detect industry against an explicit alias map (mechanism only).

        ``aliases`` maps industry id -> list of aliases. The caller (planner)
        supplies the authoritative set built from the Business Brain.
        ``generic_business`` is a fallback, never detected by alias.
        """
        low = f" {text.lower()} "
        for industry, alist in (aliases or {}).items():
            if industry == "generic_business":
                continue
            for alias in alist or []:
                if alias and alias.lower() in low:
                    return industry
        return None

    def brain_industry_aliases(self, brain: dict) -> dict:
        """Build the authoritative alias map from the Business Brain.

        The Brain is the authoritative source of industry names/aliases. The
        policy base map is merged as a lower-priority supplement so English
        and other aliases (the Brain today carries mostly Arabic aliases)
        still resolve — no second taxonomy is created; Brain names win and the
        union simply widens coverage.
        """
        profiles = (brain or {}).get("industry_profiles") or {}
        out: dict = {}
        base = (self.data.get("industry_aliases", {}) or {})
        for industry, profile in profiles.items():
            alist = profile.get("aliases") if isinstance(profile, dict) else []
            merged = []
            if isinstance(alist, list):
                merged.extend(alist)
            for a in base.get(industry) or []:  # supplement, deduped
                if a not in merged:
                    merged.append(a)
            if merged:
                out[industry] = merged
        # industries only present in the base map (not yet in the Brain)
        for industry, alist in base.items():
            if industry not in out and alist:
                out[industry] = alist
        return out

    def has_request_verb(self, text: str) -> bool:
        low = text.lower()
        return any(v in low for v in self.data["request_verbs"])

    def commercial_signal(self, text: str) -> bool:
        low = text.lower()
        return any(sig in low for sig in self.data["commercial_signals"])

    def affirmation(self, text: str) -> bool:
        low = f" {text.lower()} "
        return any(a in low for a in self.data["affirmations"])

    # ---- question engine ----------------------------------------------
    def weights_for(self, category: str | None, mode: str) -> dict:
        base = dict(self.data["question_weights"].get(category or "_default")
                    or self.data["question_weights"]["_default"])
        if mode == "COMMERCIAL":
            for field, boost in self.data["commercial_boost"].items():
                base[field] = max(base.get(field, 0), boost)
        else:
            cap = self.data["budget_weight_outside_commercial"]
            base["budget_band"] = cap
        return base

    def field_known(self, field: str, facts: dict) -> bool:
        for key in self.data["field_satisfied_by"].get(field, []):
            if facts.get(key):
                return True
        return False

    def next_question(self, category: str | None, mode: str, facts: dict,
                      exclude_field: str | None = None) -> tuple[str, str] | None:
        """Return (field, hint-in-customer-language) for the single highest
        weighted missing question, honoring the budget gate. None => no ask."""
        weights = self.weights_for(category, mode)
        best_field, best_w = None, 0
        for field, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
            if field == exclude_field or weight <= 0:
                continue
            if not self.field_known(field, facts):
                best_field, best_w = field, weight
                break
        if best_field is None or best_w <= 0:
            return None
        hint = (self.data["question_hints"].get(best_field, {}) or {}).get("en", "")
        return best_field, hint

    def question_hint(self, field: str, language: str) -> str:
        hints = self.data["question_hints"].get(field, {}) or {}
        return hints.get(language) or hints.get("en", "")

    def brain_service_id(self, category: str | None) -> str | None:
        if not category:
            return None
        spec = self.data["service_categories"].get(category) or {}
        return spec.get("brain_service_id")

    # ---- misc ----------------------------------------------------------
    @property
    def value_first_enabled(self) -> bool:
        return bool(self.data.get("value_first", True))

    @property
    def max_questions(self) -> int:
        return int(self.data.get("max_questions_per_reply", 1))

    # ---- P1 helpers ------------------------------------------------------
    def gate_b_like_scope(self, facts: dict) -> bool:
        """Scope signal strong enough to promise a tailored estimate."""
        return self.field_known("key_features", facts) and (
            self.field_known("timeline", facts) or self.field_known("scale", facts))

    def detect_style(self, text: str) -> str:
        words = len((text or "").split())
        chars = len(text or "")
        if chars <= 12 or words <= 2:
            return "short"
        if chars >= 140 or words >= 30:
            return "detailed"
        return "normal"

    def max_words_for(self, style: str) -> int:
        return int((self.data.get("style_max_words")
                    or {"short": 25, "normal": 55, "detailed": 70}).get(style, 55))

    def suggestion_clarifiers(self, industry: str | None) -> list[dict]:
        pool = self.data.get("suggestion_clarifiers", {})
        return list(pool.get(industry) or pool.get("_default") or [])

    def suggestion_skip(self, text: str) -> bool:
        low = (text or "").lower()
        return any(t in low for t in self.data.get("suggestion_skip_triggers", []))

    def detect_small_scope(self, text: str = "", facts: dict | None = None) -> bool:
        hay = " ".join([
            text or "",
            str((facts or {}).get("scope") or ""),
        ]).lower()
        return any(t in hay for t in self.data.get("small_scope_triggers", []))
