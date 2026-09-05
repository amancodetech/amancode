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
    # D3-E (transition flag, default OFF): when true AND last known coverage
    # is below threshold or has critical gaps, T2 is blocked (owner may
    # override via approval console). Enable only after D3 review.
    "coverage_block_t2": False,
    "coverage_block_threshold": 70.0,
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
    def gate_b_like_scope(self, facts: dict,
                          unknown_accepted: list | None = None) -> bool:
        """Planner-side T2 wording signal — mirrors QuoteFlow.gate_b_ready
        (D2) minus the category requirement (planner may lack it)."""
        from .pricing_flow import QuoteFlow
        try:
            return QuoteFlow.gate_b_ready(
                self, "website", facts,
                unknown_accepted=unknown_accepted)
        except Exception:  # noqa: BLE001 — wording signal never breaks plan
            return self.field_known("key_features", facts) and (
                self.field_known("timeline", facts) or self.field_known("scale", facts))

    # D1-APPROVED (safest): T1 needs shape + one other distinct group.
    # problem/desired_outcome alone do NOT count — "أريد" sets them on
    # almost every request, which would reduce the gate to category-only.
    T1_MIN_SCOPE_FACTS = (
        "scope", "timeline", "users", "pages", "page_count", "languages",
        "integrations", "payment_gateways", "gateways", "booking", "payments",
        "member_areas", "dynamic_content", "budget",
    )
    T1_GROUPS = (
        frozenset({"scope", "pages", "page_count", "booking", "payments",
                   "member_areas", "dynamic_content"}),  # shape
        frozenset({"users", "timeline"}),  # scale
        frozenset({"integrations", "payment_gateways", "gateways",
                   "languages"}),  # connect
        frozenset({"budget"}),  # money
    )

    def t1_min_scope(self, facts: dict | None,
                     unknown_accepted: list | None = None) -> bool:
        """D1: True only with >=2 facts from distinct groups incl. shape.

        unknown_accepted (D4) dims count as present for grouping.
        """
        facts = facts or {}
        present = {k for k in self.T1_MIN_SCOPE_FACTS if facts.get(k)}
        present |= {k for k in (unknown_accepted or [])
                    if k in self.T1_MIN_SCOPE_FACTS}
        groups_hit = sum(1 for g in self.T1_GROUPS if present & set(g))
        if groups_hit < 2:
            return False
        return bool(present & set(self.T1_GROUPS[0]))

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


# ---------------------------------------------------------------------------
# CIR — Contextual Intent Resolution (deterministic side only).
#
# Stage A (LLM, advisory) produces an UNTRUSTED "cir" block inside the
# extraction payload. Everything below is pure Python: validation, entity
# resolution against verified conversational evidence, temporal resolution,
# and the policy gate. No I/O, no writes, no LLM calls.
#
# Hard invariants:
#   LLM candidate != resolved entity | confidence != authorization
#   NO EVIDENCE -> NO ENTITY | multiple candidates -> AMBIGUOUS -> CLARIFY
# ---------------------------------------------------------------------------

CIR_DECISIONS = ("DENY", "CLARIFY", "CONTINUE_DISCOVERY", "ENTER_PRICING")
CIR_INTENTS = ("pricing", "timeline", "requirement", "clarification",
               "comparison", "deferral", "none")
CIR_TARGETS = ("project_price", "product_item_price", "project_timeline",
               "feature", "unknown")
CIR_ENTITIES = ("project", "product", "service", "feature", "unknown")
CIR_TEMPORALS = ("now", "later", "phase2", "unknown")

# Domain intents that veto pricing regardless of interpretation.
_CIR_VETO_DOMAINS = frozenset({"legal", "billing", "complaint", "support"})

# Deterministic CIR-trigger cues: messages that may need interpretation even
# when the extraction gate would otherwise skip the LLM (C2 override).
_CIR_QUESTION = re.compile(r"[?؟]")
_CIR_PRONOUN_ONLY = re.compile(
    r"^\s*(كم|شقد|بشقد|بكم|بكام|قديش|how much|how many|berapa)\b.{0,24}"
    r"(سعرها|سعره|ثمنها|ثمنه|تكلفتها|تكلفته|سعرهم|price|harganya|biayanya)\s*[?؟.\s]*$",
    re.IGNORECASE)
_CIR_PRICE_WORD = re.compile(
    r"(سعر|ثمن|تكلف|يكلف|تكلفة|بكم|بكام|بشحال|قديش|شقد|بشقد|price|cost|berapa|biaya|harga)",
    re.IGNORECASE)
_CIR_UNCERTAIN = re.compile(
    r"(ربما|يمكن|مو متأكد|مش متأكد|ما أدري|لا أعرف|غير متأكد|"
    r"not sure|maybe|i think|perhaps|discuss|نناقش|نتكلم|نتناقش)",
    re.IGNORECASE)

# Deterministic temporal cues (mirrors the coordinator's deferral/future
# signals minimally so this module stays self-contained and pure).
_CIR_LATER = re.compile(
    r"(لاحق|بعدين|فيما بعد|أجّل|اجل|نؤجل|later|nanti|belum|down the road|"
    r"talk.*later|discuss.*later)", re.IGNORECASE)
_CIR_PHASE2 = re.compile(
    r"(المرحلة الثانية|بعد الإطلاق|phase\s*2|future phase)", re.IGNORECASE)
_CIR_TIMELINE_ONLY = re.compile(
    r"(كم (سيأخذ|سيستغرق|يستغرق|ياخذ|المدة)|how long|berapa lama|"
    r"مدة (التنفيذ|المشروع|العمل)|timeline|duration)", re.IGNORECASE)


def cir_trigger(text: str | None) -> bool:
    """True when a message may need CIR interpretation (C2 gate override).

    Pure function. Conservative toward calling: a forced extraction call is
    always acceptable, a lost interpretation never is.
    """
    try:
        t = (text or "").strip()
        if not t:
            return False
        low = t.lower()
        words = len(t.split())
        if _CIR_PRONOUN_ONLY.search(t):
            return True
        if _CIR_PRICE_WORD.search(t):
            return True
        if _CIR_QUESTION.search(t) and words <= 4:
            return True
        if _CIR_UNCERTAIN.search(low):
            return True
        return False
    except Exception:  # noqa: BLE001 — trigger must never break intake
        return True


def sanitize_cir_block(raw: object) -> dict | None:
    """Validate an untrusted CIR block. Returns sanitized dict or None.

    Any schema/enum/range violation discards the whole block (fail-closed).
    Pure function.
    """
    try:
        if not isinstance(raw, dict):
            return None
        intent = raw.get("intent", "none")
        target = raw.get("candidate_target", "unknown")
        entity = raw.get("candidate_entity", "unknown")
        temporal = raw.get("candidate_temporal", "unknown")
        ambiguity = raw.get("ambiguity", False)
        confidence = raw.get("confidence", 0.0)
        if intent not in CIR_INTENTS:
            return None
        if target not in CIR_TARGETS:
            return None
        if entity not in CIR_ENTITIES:
            return None
        if temporal not in CIR_TEMPORALS:
            return None
        if not isinstance(ambiguity, bool):
            return None
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return None
        if not 0.0 <= float(confidence) <= 1.0:
            return None
        ref = raw.get("candidate_reference")
        if ref is not None and not isinstance(ref, str):
            return None
        return {
            "intent": intent,
            "candidate_target": target,
            "candidate_entity": entity,
            "candidate_reference": ref,
            "candidate_temporal": temporal,
            "ambiguity": ambiguity,
            # recorded for observability only — NEVER an authorization input
            "confidence": float(confidence),
        }
    except Exception:  # noqa: BLE001 — validation must never break intake
        return None


def resolve_cir_entity(cir: dict | None, *, explicit: list,
                       active_category: str | None,
                       reference_confirmed: str | None = None,
                       named_product: str | None = None) -> dict:
    """Deterministic entity resolution (Stage B). Pure function.

    ``cir`` is the SANITIZED advisory block (or None when unavailable).
    ``explicit`` lists service categories named in the CURRENT message.
    Never invents an entity: no evidence -> unknown; competing referents ->
    ambiguous. ``named_product`` stays None until a verified product-entity
    representation exists (UNKNOWN/BLOCKED) — product candidates therefore
    resolve to ambiguous by construction.
    """
    try:
        explicit = [e for e in (explicit or []) if e]
        competing: list[str] = []
        if cir is None:
            return {"status": "unknown", "entity": None,
                    "evidence_source": "none", "evidence_strength": "none",
                    "competing_candidates": competing}
        candidate = cir.get("candidate_entity", "unknown")
        if candidate == "product" and not named_product:
            # forbidden inference: absence of project context is NOT
            # evidence of a product; without an independently verified
            # product entity the safe state is ambiguous.
            if active_category or explicit:
                competing = ["project"]
            return {"status": "ambiguous", "entity": None,
                    "evidence_source": "none", "evidence_strength": "none",
                    "competing_candidates": competing or ["unverified_product"]}
        if cir.get("ambiguity"):
            return {"status": "ambiguous", "entity": None,
                    "evidence_source": "none", "evidence_strength": "weak",
                    "competing_candidates": competing}
        if len(explicit) >= 2:
            return {"status": "ambiguous", "entity": None,
                    "evidence_source": "explicit_current",
                    "evidence_strength": "explicit",
                    "competing_candidates": list(explicit[:4])}
        if len(explicit) == 1:
            return {"status": "resolved", "entity": "project",
                    "evidence_source": "explicit_current",
                    "evidence_strength": "explicit",
                    "competing_candidates": []}
        # no explicit entity in the current message: fall back to verified
        # conversational state, never to the candidate alone.
        if active_category and candidate == "project":
            return {"status": "resolved", "entity": "project",
                    "evidence_source": "active_category",
                    "evidence_strength": "supported",
                    "competing_candidates": []}
        if reference_confirmed and candidate == "project":
            return {"status": "resolved", "entity": "project",
                    "evidence_source": "confirmed_reference",
                    "evidence_strength": "supported",
                    "competing_candidates": []}
        return {"status": "unknown", "entity": None,
                "evidence_source": "none", "evidence_strength": "none",
                "competing_candidates": competing}
    except Exception:  # noqa: BLE001 — resolution must never break intake
        return {"status": "unknown", "entity": None,
                "evidence_source": "none", "evidence_strength": "none",
                "competing_candidates": []}


def resolve_cir_temporal(cir: dict | None, text: str | None) -> str:
    """Deterministic temporal resolution. Pure function.

    Deterministic cues win over the advisory candidate. Absence of deferral
    evidence means "unknown" (callers treat unknown+pricing as now) — never
    assumed "later".
    """
    try:
        t = text or ""
        if _CIR_PHASE2.search(t):
            return "phase2"
        if _CIR_LATER.search(t):
            return "later"
        if cir is not None and cir.get("candidate_temporal") in ("later", "phase2"):
            # advisory only reaches here when no deterministic cue fired;
            # a later/phase2 claim still defers (safe direction).
            return str(cir["candidate_temporal"])
        if cir is not None and cir.get("intent") == "timeline":
            return "unknown"
        if _CIR_TIMELINE_ONLY.search(t):
            return "unknown"
        return "now" if cir is not None and cir.get("intent") == "pricing" else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def cir_policy_decision(*, price_intent: str, cir: dict | None,
                        entity: dict, temporal: str,
                        domain_intent: str = "",
                        scope_under_review: bool = False) -> str:
    """Deterministic policy gate (Stage C). Pure function, no LLM.

    Returns one of CIR_DECISIONS. ``cir`` must already be sanitized (or
    None). Confidence is never read here by construction.
    """
    try:
        if (domain_intent or "") in _CIR_VETO_DOMAINS:
            return "DENY"
        if scope_under_review:
            return "DENY"
        if price_intent == "deferral":
            return "CONTINUE_DISCOVERY"
        if temporal in ("later", "phase2"):
            return "CONTINUE_DISCOVERY"
        if cir is not None and cir.get("intent") == "timeline":
            return "CONTINUE_DISCOVERY"
        if cir is not None and cir.get("intent") == "deferral":
            return "CONTINUE_DISCOVERY"
        status = (entity or {}).get("status", "unknown")
        resolved = (entity or {}).get("entity")
        wants_pricing = price_intent == "direct_ask" or (
            cir is not None and cir.get("intent") == "pricing")
        if not wants_pricing:
            return "CONTINUE_DISCOVERY"
        # Legacy-compatible fallback: with NO interpretation available at
        # all (LLM skipped/unavailable), the pre-CIR behavior stands verbatim.
        if cir is None and status == "unknown":
            return "ENTER_PRICING" if price_intent == "direct_ask" else "CONTINUE_DISCOVERY"
        if status == "resolved" and resolved == "project":
            return "ENTER_PRICING"
        if status in ("ambiguous", "unknown"):
            return "CLARIFY"
        return "CLARIFY"
    except Exception:  # noqa: BLE001 — gate must never break intake
        return "CONTINUE_DISCOVERY"
