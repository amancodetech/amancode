"""Conflict Detector — identifies mutual exclusions, contradictions, and scope conflicts in requirements and decisions."""

from __future__ import annotations

import logging
from typing import Any

from .models import RequirementConflict

log = logging.getLogger("amancore.requirements.conflicts")


class ConflictDetector:
    """Detects logical and architectural conflicts across requirements."""

    CONFLICT_RULES = [
        # (Subcategory A, Subcategory B, conflict_type, explanation EN, explanation AR)
        (
            "no_auth", "auth_members",
            "mutual_exclusion",
            "Customer requested a public system with no login, but also specified private user accounts.",
            "العميل طلب نظامًا عامًا بدون تسجيل دخول، وطلب في الوقت نفسه حسابات مستخدمين خاصة.",
        ),
        (
            "offline_only", "payments",
            "scope_contradiction",
            "Customer requested cash-only payments, but also requested online card/gateway checkout.",
            "العميل حدد الدفع عند الاستلام فقط، وطلب في الوقت نفسه بوابة دفع إلكتروني بالبطاقات.",
        ),
        (
            "static_presence", "inventory",
            "logic_mismatch",
            "A static presence starter scope does not support real-time dynamic inventory tracking.",
            "باقة التواجد البسيط (Static) لا تدعم نظام تتبع وإدارة المخزون الفوري.",
        ),
    ]

    def detect_conflicts(
        self,
        requirements: list[dict],
        decisions: list[dict] | None = None,
        lead_id: str | None = None,
        project_id: str | None = None,
    ) -> list[RequirementConflict]:
        """Examine active requirements to detect contradictions."""
        conflicts: list[RequirementConflict] = []
        req_by_subcat = {
            r.get("subcategory"): r
            for r in requirements
            if r.get("subcategory") and r.get("requirement_id")
        }

        # Requirement vs Requirement conflicts (strictly validated foreign keys)
        for sub_a, sub_b, ctype, expl_en, expl_ar in self.CONFLICT_RULES:
            if sub_a in req_by_subcat and sub_b in req_by_subcat:
                req_a = req_by_subcat[sub_a]
                req_b = req_by_subcat[sub_b]
                req_a_id = req_a.get("requirement_id")
                req_b_id = req_b.get("requirement_id")

                if req_a_id and req_b_id:
                    conflicts.append(
                        RequirementConflict(
                            lead_id=lead_id,
                            project_id=project_id,
                            requirement_a_id=req_a_id,
                            requirement_b_id=req_b_id,
                            conflict_type=ctype,
                            explanation=expl_en,
                            status="open",
                        )
                    )
                    log.info(
                        "conflict.detected lead=%s type=%s req_a=%s req_b=%s",
                        lead_id, ctype, req_a_id, req_b_id,
                    )

        return conflicts
