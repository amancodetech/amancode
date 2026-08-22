"""Intent routing — deterministic first; LLM-assist is optional.

Two levels:
- domain: which agent/owner handles the message (sales | support | billing | legal | complaint | general)
- support category: granular support classification (9 categories)

Domain rules (spec section 34):
    sales     -> SalesAgent
    support   -> SupportAgent
    billing   -> Owner (via support case + escalation)
    legal     -> Owner / Legal review
    complaint -> Support + escalation
    general   -> routed by context (customer -> SupportAgent, prospect -> SalesAgent)
"""

from __future__ import annotations

import re

SUPPORT_CATEGORIES = (
    "sales", "existing_customer", "technical_support", "billing",
    "complaint", "legal", "project_status", "feature_request", "general",
)

DOMAINS = ("sales", "support", "billing", "legal", "complaint", "general")

_LEGAL = re.compile(
    r"\b(legal|lawyer|lawsuit|sue|suing|court|contract breach|breach of contract|attorney|قانون|محام|قضية|دعوى|hukum|pengacara|tuntutan)\b",
    re.IGNORECASE,
)
_COMPLAINT = re.compile(
    r"\b(complaint|angry|furious|terrible|awful|scam|fraud|ripoff|rip off|never again|شكوى|غاضب|غش|نصب|keluhan|penipuan|marah)\b",
    re.IGNORECASE,
)
_BILLING = re.compile(
    r"\b(refund|reimburse|overcharge|charged twice|invoice|payment|billing|bill|money back|استرداد|فاتورة|دفع|tagihan|bayar|uang kembali)\b",
    re.IGNORECASE,
)
_SECURITY_CRITICAL = re.compile(
    r"\b(security incident|data breach|hacked|leaked|credentials stolen|service down|completely unavailable|emergency|اختراق|تسريب|قرصنة|bocor|diretas|darurat)\b",
    re.IGNORECASE,
)
_SUPPORT = re.compile(
    r"\b(support|help|problem|broken|error|not working|issue|fix|maintenance|دعم|مشكلة|مساعدة|خطأ|masalah|bantuan|rusak|error|perbaikan)\b",
    re.IGNORECASE,
)
_SALES = re.compile(
    r"\b(buy|price|quote|website|web app|mobile app|hire|order|proposal|cost|أريد|شراء|سعر|موقع|طلب|mau|beli|harga|pesan)\b",
    re.IGNORECASE,
)
_PROJECT_STATUS = re.compile(
    r"\b(project status|status of my project|how is my project|progress|when will it be done|deadline|release date|تقدم|مشروعي|kapan selesai|progress)\b",
    re.IGNORECASE,
)
_FEATURE_REQUEST = re.compile(
    r"\b(add feature|new feature|can you add|want to add|i need extra|إضافة ميزة|tambah fitur)\b",
    re.IGNORECASE,
)
_TECHNICAL = re.compile(
    r"\b(error|bug|crash|broken|not working|doesn't work|login problem|site down|error message|خطأ|عطل|tidak jalan|rusak|bug)\b",
    re.IGNORECASE,
)
_EXISTING_CUSTOMER = re.compile(
    r"\b(my project|my website|my app|my account|as a customer|عميل|مشروعي|pelanggan|akun saya)\b",
    re.IGNORECASE,
)


class IntentRouter:
    """Deterministic intent classification (no LLM dependency)."""

    def classify_domain(self, message: str) -> str:
        text = (message or "").lower()
        if _SECURITY_CRITICAL.search(text):
            return "support"  # CRITICAL path handled by SupportAgent
        if _LEGAL.search(text):
            return "legal"
        if _COMPLAINT.search(text):
            return "complaint"
        if _BILLING.search(text):
            return "billing"
        if _SUPPORT.search(text) or _TECHNICAL.search(text) or _PROJECT_STATUS.search(text):
            return "support"
        if _SALES.search(text):
            return "sales"
        if _EXISTING_CUSTOMER.search(text):
            return "support"
        return "general"

    def classify_category(self, message: str) -> str:
        """9-category support classification."""
        text = (message or "").lower()
        if _SECURITY_CRITICAL.search(text):
            return "technical_support"  # treated as CRITICAL priority separately
        if _LEGAL.search(text):
            return "legal"
        if _COMPLAINT.search(text):
            return "complaint"
        if _BILLING.search(text):
            return "billing"
        if _PROJECT_STATUS.search(text):
            return "project_status"
        if _FEATURE_REQUEST.search(text):
            return "feature_request"
        if _TECHNICAL.search(text):
            return "technical_support"
        if _SALES.search(text):
            return "sales"
        if _EXISTING_CUSTOMER.search(text):
            return "existing_customer"
        return "general"

    def priority_for(self, category: str, support_policy: dict | None = None) -> str:
        """Map category -> priority using the configurable support policy."""
        prio_cfg = (support_policy or {}).get("priority", {})
        return prio_cfg.get(category, prio_cfg.get("general", "LOW")).upper()

    def is_critical(self, message: str) -> bool:
        return bool(_SECURITY_CRITICAL.search(message or ""))
