"""Coverage Analyzer — calculates Discovery Coverage % and identifies gaps across the AmanCode Service Ladder."""

from __future__ import annotations

import logging
from typing import Any

from .models import CoverageReport

log = logging.getLogger("amancore.requirements.coverage")


class CoverageAnalyzer:
    """Evaluates how completely a client's project requirements have been discovered."""

    # Domains required per Service Ladder Tier
    TIER_DOMAINS = {
        "website": {
            "core_structure": {"weight": 25, "critical": True, "label": "Page Structure & Scope"},
            "whatsapp_intake": {"weight": 20, "critical": True, "label": "WhatsApp Intake & Contact"},
            "localization": {"weight": 20, "critical": True, "label": "Language & Market"},
            "brand_assets": {"weight": 20, "critical": False, "label": "Logo & Brand Assets"},
            "timeline_budget": {"weight": 15, "critical": False, "label": "Timeline & Budget Target"},
        },
        "web_app": {
            "core_workflow": {"weight": 25, "critical": True, "label": "Custom Business Workflow"},
            "auth_roles": {"weight": 20, "critical": True, "label": "Authentication & User Roles"},
            "database_entities": {"weight": 20, "critical": True, "label": "Data Models & Records"},
            "integrations": {"weight": 20, "critical": False, "label": "Third-Party APIs & Services"},
            "timeline_budget": {"weight": 15, "critical": False, "label": "Timeline & Budget Target"},
        },
        "mini_erp": {
            "sales_invoicing": {"weight": 25, "critical": True, "label": "Sales, Billing & Invoicing"},
            "inventory_stock": {"weight": 25, "critical": True, "label": "Inventory & Stock Tracking"},
            "staff_roles": {"weight": 20, "critical": True, "label": "Staff Permissions & Hierarchy"},
            "reports_analytics": {"weight": 15, "critical": False, "label": "Reports & Financial Summaries"},
            "timeline_budget": {"weight": 15, "critical": False, "label": "Timeline & Budget Target"},
        },
        "mobile": {
            "mobile_platforms": {"weight": 25, "critical": True, "label": "Target Platforms (iOS / Android)"},
            "core_app_features": {"weight": 25, "critical": True, "label": "Core Mobile Features"},
            "api_backend": {"weight": 20, "critical": True, "label": "Backend System Connection"},
            "notifications": {"weight": 15, "critical": False, "label": "Push Notifications"},
            "timeline_budget": {"weight": 15, "critical": False, "label": "Timeline & Budget Target"},
        },
    }

    def analyze(
        self,
        tier: str = "website",
        requirements: list[dict] | None = None,
        decisions: list[dict] | None = None,
        facts: dict[str, Any] | None = None,
    ) -> CoverageReport:
        """Calculate coverage score and discoverable missing domains."""
        tier_key = str(tier or "website").lower().strip()
        if tier_key not in self.TIER_DOMAINS:
            tier_key = "website"

        domain_specs = self.TIER_DOMAINS[tier_key]
        reqs = requirements or []
        if isinstance(decisions, dict):
            decs = decisions
        else:
            decs = {
                d.get("topic"): d.get("decision")
                for d in (decisions or [])
                if isinstance(d, dict) and d.get("status", "active") == "active"
            }
        known_facts = facts or {}

        covered: list[str] = []
        missing: list[str] = []
        critical_gaps: list[str] = []
        total_score = 0.0

        for domain, spec in domain_specs.items():
            is_covered = self._is_domain_covered(domain, reqs, decs, known_facts)
            if is_covered:
                covered.append(spec["label"])
                total_score += spec["weight"]
            else:
                missing.append(spec["label"])
                if spec["critical"]:
                    critical_gaps.append(spec["label"])

        final_score = max(0.0, min(100.0, total_score))
        is_ready = (final_score >= 70.0) and (len(critical_gaps) == 0)

        log.debug(
            "coverage.analyzed tier=%s score=%.1f ready=%s covered=%d missing=%d",
            tier_key, final_score, is_ready, len(covered), len(missing),
        )

        return CoverageReport(
            tier=tier_key,
            coverage_score=final_score,
            covered_domains=covered,
            missing_domains=missing,
            critical_gaps=critical_gaps,
            is_ready_for_proposal=is_ready,
        )

    def _is_domain_covered(
        self,
        domain: str,
        requirements: list[dict],
        decisions: dict[str, str],
        facts: dict[str, Any],
    ) -> bool:
        categories = {r.get("category") for r in requirements if r.get("category")}
        subcategories = {r.get("subcategory") for r in requirements if r.get("subcategory")}

        if domain == "core_structure":
            return bool("ecommerce" in subcategories or "booking" in subcategories or "core_module" in categories or facts.get("scope"))
        if domain == "whatsapp_intake":
            return bool("messaging" in subcategories or "integrations" in subcategories or "whatsapp" in decisions)
        if domain == "localization":
            return bool("languages" in decisions or facts.get("languages"))
        if domain == "brand_assets":
            return bool("dynamic_content" in subcategories or facts.get("logo") or facts.get("brand"))
        if domain == "timeline_budget":
            return bool("currency" in decisions or facts.get("budget") or facts.get("timeline"))
        if domain == "core_workflow":
            return bool("core_module" in categories or facts.get("problem") or facts.get("desired_outcome"))
        if domain == "auth_roles":
            return bool("auth_members" in subcategories or "admin" in subcategories or facts.get("users"))
        if domain == "database_entities":
            return bool("core_module" in categories or len(requirements) >= 2)
        if domain == "integrations":
            return bool("payments" in subcategories or "shipping" in subcategories or "messaging" in subcategories or "integration" in categories)
        if domain == "sales_invoicing":
            return bool("invoicing" in subcategories or "payments" in subcategories)
        if domain == "inventory_stock":
            return bool("inventory" in subcategories or "ecommerce" in subcategories)
        if domain == "staff_roles":
            return bool("admin" in subcategories or facts.get("users") or facts.get("authority"))
        if domain == "reports_analytics":
            return bool("admin" in subcategories or "invoicing" in subcategories)
        if domain == "mobile_platforms":
            return bool("mobile_app" in subcategories or facts.get("mobile"))
        if domain == "core_app_features":
            return bool("mobile_app" in subcategories or len(requirements) >= 2)
        if domain == "api_backend":
            return bool("integration" in categories or len(requirements) >= 2)
        if domain == "notifications":
            return bool("messaging" in subcategories)

        return False
