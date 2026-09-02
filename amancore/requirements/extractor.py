"""Requirements Extractor — extracts explicit and inferred requirements, decisions, and constraints from customer messages."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .models import Certainty, Priority, ProjectDecision, Requirement, Status

log = logging.getLogger("amancore.requirements.extractor")


class RequirementsExtractor:
    """Deterministic and LLM-assisted requirement extraction engine."""

    # ── Feature / Module Patterns ──────────────────────────────────────────
    MODULE_RULES = [
        # (Pattern regex, Category, Subcategory, Title EN, Title AR)
        (
            r"متجر|ecommerce|online store|e-commerce|toko online|بيع أونلاين|منتجات|سلة مشتريات",
            "core_module", "ecommerce",
            "E-Commerce & Product Catalog", "نظام المتجر الإلكتروني وكتالوج المنتجات",
        ),
        (
            r"حجز|حجوزات|booking|reservation|reservasi|جدول مواعيد|موعد|عيادة|طبيب",
            "core_module", "booking",
            "Booking & Reservation System", "نظام الحجوزات وإدارة المواعيد",
        ),
        (
            r"دفع|بوابة دفع|مدفوعات|payment|checkout|midtrans|stripe|paypal|bayar|visa|mastercard|مدى|mada",
            "integration", "payments",
            "Online Payment Gateway Integration", "ربط بوابة الدفع الإلكتروني",
        ),
        (
            r"واتساب|whatsapp|notifikasi wa|إشعارات واتساب|رسائل واتساب",
            "integration", "messaging",
            "WhatsApp Business API & Notifications", "ربط وإشعارات واتساب للأعمال",
        ),
        (
            r"عضويات|أعضاء|تسجيل دخول|حسابات مستخدمين|portal|membership|login|member area|user account|login pengguna",
            "core_module", "auth_members",
            "User Accounts & Member Portal", "بوابة الأعضاء وتسجيل الدخول",
        ),
        (
            r"لوحة تحكم|إدارة|admin dashboard|dashboard|cpanel|panel admin|إدارة الطلبات",
            "core_module", "admin",
            "Admin Management Dashboard", "لوحة تحكم الإدارة والعمليات",
        ),
        (
            r"مخزون|مستودع|inventory|stock|gudang|تتبع المخزون",
            "core_module", "inventory",
            "Inventory & Stock Tracking", "نظام إدارة وتتبع المخزون",
        ),
        (
            r"فواتير|محاسبة|invoicing|billing|faktur|accounting|سندات",
            "core_module", "invoicing",
            "Invoicing & Accounting Engine", "نظام الفوترة والمحاسبة المالية",
        ),
        (
            r"تطبيق جوال|تطبيق هاتف|mobile app|android|ios|flutter|aplikasi mobile",
            "core_module", "mobile_app",
            "Mobile Application (iOS & Android)", "تطبيق الجوال (iOS وأندرويد)",
        ),
        (
            r"ذكاء اصطناعي|بوت|أتمتة|ai agent|chatbot|automation|otomasi|رد آلي",
            "core_module", "ai_automation",
            "AI Agent & Workflow Automation", "وكيل الذكاء الاصطناعي وأتمتة العمليات",
        ),
        (
            r"شحن|توصيل|شركات شحن|shipping|delivery|kurir|tracking|تتبع الشحنة",
            "integration", "shipping",
            "Shipping & Delivery Carrier Integration", "ربط شركات الشحن والتوصيل والتتبع",
        ),
        (
            r"مدونة|أخبار|مقالات|blog|news|articles|berita|معرض صور|gallery",
            "ui_ux", "dynamic_content",
            "Dynamic Blog / News & Gallery System", "نظام المدونة الإخبارية ومعرض الوسائط",
        ),
    ]

    # ── Decisions Patterns (Currency, Languages, Tech, etc.) ───────────────
    DECISION_RULES = [
        # (Pattern, Topic, Decision Value, Label)
        (
            r"\b(idr|rupiah|روبية|rp)\b",
            "currency", "IDR", "Indonesian Rupiah",
        ),
        (
            r"\b(usd|dollar|دولار|\$)\b",
            "currency", "USD", "US Dollar",
        ),
        (
            r"\b(sar|ريال سعودي|ريال)\b",
            "currency", "SAR", "Saudi Riyal",
        ),
        (
            r"\b(aed|درهم|درهم إماراتي)\b",
            "currency", "AED", "UAE Dirham",
        ),
        (
            r"عربي\s*و\s*إنجليزي|arabic\s*and\s*english|bilingual|لغتين|dua bahasa",
            "languages", "Arabic + English", "Bilingual Support (Arabic & English)",
        ),
        (
            r"إندونيسي\s*و\s*إنجليزي|indonesian\s*and\s*english|bahasa indonesia",
            "languages", "Indonesian + English", "Bilingual Support (Indonesian & English)",
        ),
        (
            r"عربي\s*فقط|arabic only|فقط عربي",
            "languages", "Arabic Only", "Single Language (Arabic)",
        ),
    ]

    # Negation pattern supporting Arabic prefix conjunctions (و, ف) and EN/ID negations
    NEGATION_PATTERN = re.compile(
        r"(?:^|\s|[وف])(?:لا|ما|بدون|بلا|دون|ليس|no|not|without|tanpa|nggak|bukan)\b",
        re.IGNORECASE,
    )

    def extract(
        self,
        message: str,
        lead_id: str | None = None,
        project_id: str | None = None,
        source_message_id: str | None = None,
        source_conversation_id: str | None = None,
    ) -> dict[str, list[Any]]:
        """Extract all requirements, decisions, and constraints from a single customer message."""
        text = (message or "").strip()
        if not text:
            return {"requirements": [], "decisions": []}

        low = f" {text.lower()} "

        extracted_requirements: list[Requirement] = []
        extracted_decisions: list[ProjectDecision] = []

        # 1. Module & Feature Extraction
        for pat, cat, subcat, title_en, title_ar in self.MODULE_RULES:
            match = re.search(pat, low, re.IGNORECASE)
            if match:
                # Check for explicit negation in pre-match window ("بدون دفع", "وبلا تسجيل دخول", "no payments", "tanpa login")
                window = low[max(0, match.start() - 25) : match.start()]
                is_negated = bool(self.NEGATION_PATTERN.search(window))
                if is_negated:
                    continue

                # Determine if explicit vs inferred
                is_direct_ask = bool(
                    re.search(
                        r"أريد|نحتاج|أحتاج|أبي|ابغى|نرغب|لازم|مطلوب|يجب|want|need|looking for|require|butuh|mau|tolong",
                        low,
                        re.IGNORECASE,
                    )
                )

                certainty = Certainty.EXPLICIT.value if is_direct_ask else Certainty.INFERRED.value
                confidence = 0.98 if is_direct_ask else 0.85

                # Detect language of statement for title
                is_arabic = bool(re.search(r"[\u0600-\u06FF]", text))
                title = title_ar if is_arabic else title_en
                description = f"Requirement identified from customer message: \"{text[:200]}\""

                req = Requirement(
                    title=title,
                    description=description,
                    category=cat,
                    subcategory=subcat,
                    priority=Priority.MUST_HAVE.value,
                    certainty=certainty,
                    confidence=confidence,
                    status=Status.CAPTURED.value,
                    source_message_id=source_message_id,
                    source_conversation_id=source_conversation_id,
                    lead_id=lead_id,
                    project_id=project_id,
                    is_customer_requested=True,
                    is_system_inferred=(certainty == Certainty.INFERRED.value),
                )
                extracted_requirements.append(req)

        # 2. Decision Extraction
        for pat, topic, dec_val, dec_label in self.DECISION_RULES:
            if re.search(pat, low, re.IGNORECASE):
                dec = ProjectDecision(
                    topic=topic,
                    decision=dec_val,
                    rationale=f"Customer specified {dec_label}",
                    source_message_id=source_message_id,
                    lead_id=lead_id,
                    project_id=project_id,
                    decided_by="customer",
                    status="active",
                )
                extracted_decisions.append(dec)

        log.debug(
            "extract.completed lead=%s reqs=%d decs=%d",
            lead_id, len(extracted_requirements), len(extracted_decisions),
        )

        return {
            "requirements": extracted_requirements,
            "decisions": extracted_decisions,
        }

    def parse_llm_json(
        self,
        raw_output: Any,
        lead_id: str | None = None,
        project_id: str | None = None,
        source_message_id: str | None = None,
        source_conversation_id: str | None = None,
    ) -> dict[str, list[Any]]:
        """Safely validate, sanitize and parse structured LLM json extraction into typed dataclasses."""
        reqs: list[Requirement] = []
        decs: list[ProjectDecision] = []

        data = raw_output
        if isinstance(raw_output, str):
            clean_str = raw_output.strip()
            # Strip markdown code fences if present
            if clean_str.startswith("```"):
                clean_str = re.sub(r"^```(?:json)?\s*", "", clean_str)
                clean_str = re.sub(r"\s*```$", "", clean_str)
            try:
                data = json.loads(clean_str)
            except Exception:
                log.warning("parse_llm_json failed to decode json: %s", str(raw_output)[:100])
                return {"requirements": [], "decisions": []}

        if not isinstance(data, dict):
            return {"requirements": [], "decisions": []}

        # Parse requirements list
        for item in data.get("requirements", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue

            category = str(item.get("category") or "core_module").strip()
            subcategory = str(item.get("subcategory") or "").strip() or None
            description = str(item.get("description") or title).strip()
            certainty = str(item.get("certainty") or Certainty.INFERRED.value).lower().strip()
            priority = str(item.get("priority") or Priority.MUST_HAVE.value).lower().strip()

            try:
                conf = float(item.get("confidence", 0.9))
            except (TypeError, ValueError):
                conf = 0.9

            req = Requirement(
                title=title[:200],
                description=description[:2000],
                category=category[:64],
                subcategory=subcategory[:64] if subcategory else None,
                priority=priority,
                certainty=certainty,
                confidence=conf,
                source_message_id=source_message_id,
                source_conversation_id=source_conversation_id,
                lead_id=lead_id,
                project_id=project_id,
                is_customer_requested=(certainty == Certainty.EXPLICIT.value),
                is_system_inferred=(certainty != Certainty.EXPLICIT.value),
            )
            reqs.append(req)

        # Parse decisions list
        for d in data.get("decisions", []):
            if not isinstance(d, dict):
                continue
            topic = str(d.get("topic") or "").strip()
            val = str(d.get("decision") or d.get("value") or "").strip()
            if topic and val:
                decs.append(
                    ProjectDecision(
                        topic=topic[:64],
                        decision=val[:255],
                        rationale=str(d.get("rationale") or "")[:2000] or None,
                        source_message_id=source_message_id,
                        lead_id=lead_id,
                        project_id=project_id,
                        decided_by="customer",
                        status="active",
                    )
                )

        return {"requirements": reqs, "decisions": decs}
