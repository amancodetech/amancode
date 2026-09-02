"""Question Engine — computes prioritized next discovery questions based on coverage gaps and impact."""

from __future__ import annotations

import logging
from typing import Any

from .models import OpenQuestion

log = logging.getLogger("amancore.requirements.questions")


class QuestionEngine:
    """Prioritizes and selects the single most valuable missing discovery question."""

    QUESTION_BANK = [
        # (Topic/Gap, Base Weight, Impact, Missingness, Ambiguity, Question EN, Question AR, Question ID)
        (
            "core_structure", 95, 1.0, 1.0, 0.95,
            "What core pages or modules are most critical for your business launch?",
            "ما هي الصفحات أو الأقسام الأساسية الأكثر أهمية لإنطلاق مشروعك؟",
            "Halaman atau modul utama apa yang paling penting untuk peluncuran bisnis Anda?",
        ),
        (
            "ecommerce", 90, 0.95, 1.0, 0.95,
            "How many products or categories are you planning to sell online?",
            "كم عدد المنتجات أو الفئات التي تخطط لعرضها وبيعها في المتجر؟",
            "Berapa banyak produk atau kategori yang Anda rencanakan untuk dijual online?",
        ),
        (
            "payments", 85, 0.90, 1.0, 0.95,
            "What payment methods do your customers use most (e.g. Card, Bank Transfer, Apple Pay, QRIS)?",
            "ما هي طرق الدفع المفضلة لدى عملائك (مثلاً: مدى/بطاقات، تحويل بنكي، أبل باي، كاش)؟",
            "Metode pembayaran apa yang paling sering digunakan pelanggan Anda (misal: Transfer, Kartu, QRIS, COD)?",
        ),
        (
            "localization", 80, 0.85, 1.0, 0.95,
            "Which languages should the platform support from day one?",
            "ما هي اللغات التي يجب أن يدعمها النظام من اليوم الأول؟",
            "Bahasa apa saja yang harus didukung platform sejak hari pertama?",
        ),
        (
            "auth_roles", 75, 0.80, 1.0, 0.95,
            "Who will access the admin area, and what permissions will your staff need?",
            "من سيستخدم لوحة الإدارة، وما هي الصلاحيات التي يحتاجها فريق عملك؟",
            "Siapa saja yang akan mengakses area admin, dan izin apa yang dibutuhkan staf Anda?",
        ),
        (
            "brand_assets", 60, 0.70, 0.9, 0.95,
            "Do you already have your logo, branding, and content ready, or will you need design support?",
            "هل الشعار وهوية العلامة والمحتوى جاهزة لديك، أم ترغب في تصميمها وتجهيزها؟",
            "Apakah Anda sudah memiliki logo, branding, dan konten, atau butuh bantuan desain?",
        ),
        (
            "timeline_budget", 55, 0.65, 0.9, 0.95,
            "What is your target launch date for this system?",
            "ما هو الموعد التقريبي المستهدف لإطلاق النظام وبدء العمل؟",
            "Kapan target peluncuran sistem ini?",
        ),
    ]

    def select_best_question(
        self,
        coverage_report,
        decisions: dict[str, str],
        requirements: list[dict],
        answered_categories: set[str] | None = None,
        language: str = "ar",
    ) -> OpenQuestion | None:
        """Select the highest-priority question that has not been addressed or answered yet."""
        subcategories = {r.get("subcategory") for r in requirements if r.get("subcategory")}
        decided_topics = set(decisions.keys())
        answered = answered_categories or set()

        for gap_key, base_wt, impact, miss, amb, q_en, q_ar, q_id in self.QUESTION_BANK:
            # Skip if already answered previously in open_questions
            if gap_key in answered:
                continue

            # Skip if already captured in requirements or decisions
            if gap_key == "core_structure" and ("ecommerce" in subcategories or "booking" in subcategories):
                continue
            if gap_key == "ecommerce" and "ecommerce" not in subcategories:
                continue
            if gap_key == "payments" and ("payments" in subcategories or "payment_gateway" in decided_topics):
                continue
            if gap_key == "localization" and "languages" in decided_topics:
                continue
            if gap_key == "auth_roles" and "auth_members" in subcategories:
                continue
            if gap_key == "brand_assets" and ("brand" in decided_topics or "dynamic_content" in subcategories):
                continue
            if gap_key == "timeline_budget" and ("timeline" in decided_topics or "currency" in decided_topics):
                continue

            # Calculate mathematical priority formula
            # Priority = round(Impact * Missingness * Ambiguity * BaseWeight) clamped to [1, 100]
            computed_priority = max(1, min(100, int(round(base_wt * impact * miss * amb))))

            # Pick text by language
            lang = str(language or "en").lower().strip()
            text = q_ar if lang == "ar" else (q_id if lang == "id" else q_en)

            log.info(
                "question.selected gap=%s priority=%d lang=%s",
                gap_key, computed_priority, lang,
            )

            return OpenQuestion(
                question=text,
                priority=computed_priority,
                category=gap_key,
                reason=f"High-impact discovery gap in {gap_key} (priority {computed_priority})",
            )

        return None
