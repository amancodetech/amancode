"""QualityGuard — P0-5 pre-send quality gate (planned sales turns only).

Checks the FINAL customer-facing text against the ResponsePlan that
authorized it:

    1. no numbers outside the plan's authorized figures
    2. no foreign catalog/service names (cross-service hallucination)
       and no forbidden-claim phrasing
    3. at most ONE question
    4. no parroting of already-known facts / echoing the customer
    5. language matches the customer's detected language (ar enforced)
    6. mode consistency: no budget ask outside COMMERCIAL

The legacy path (plan=None) bypasses the guard completely.
"""

from __future__ import annotations

import re

_NUM_RE = re.compile(r"\d[\d.,]*")
_AR_RE = re.compile(r"[\u0600-\u06FF]")
_QUESTIONS = ("?", "؟")
_CURRENCY_RE = re.compile(r"\b(usd|sar|idr|myr|sgd|us\$|دولار|ريال|روبية)\b")

_FORBIDDEN_PHRASES = [
    "guarantee", "we guarantee", "نضمن", "ضمان الزيادة", "زيادة مضمونة",
    "100+ clients", "more than 100 clients", "أكثر من 100 عميل",
    "certified by", "معتمدون من",
]


def _norm_number(token: str) -> str:
    return token.replace(",", "").replace(".", "").lstrip("0") or "0"


class QualityGuard:
    def __init__(self, policy=None):
        self.policy = policy

    @staticmethod
    def _is_repeat(a: str, b: str, threshold: float = 0.85) -> bool:
        """Advisory near-duplicate detector (bigram Jaccard)."""
        na, nb = (a or "").lower(), (b or "").lower()
        if len(na) < 20 or len(nb) < 20:
            return False
        ba = {na[i:i + 2] for i in range(len(na) - 1)}
        bb = {nb[i:i + 2] for i in range(len(nb) - 1)}
        if not ba or not bb:
            return False
        return len(ba & bb) / len(ba | bb) >= threshold

    def check(self, text: str, *, plan: dict | None = None,
              last_customer_text: str | None = None,
              recent_replies: list[str] | None = None) -> dict:
        if plan is None:
            return {"allowed": True, "violations": [], "advisories": []}
        violations: list[str] = []
        advisories: list[str] = []
        quality = plan.get("quality") or {}
        allowed_nums = {_norm_number(n) for n in quality.get("allowed_numbers", [])}

        # 1 — numbers
        for tok in _NUM_RE.findall(text or ""):
            if _norm_number(tok) not in allowed_nums:
                violations.append(f"unauthorized_number:{tok}")
                break

        # 1b — currency consistency: only enforced when the plan declares an
        # approved currency (no declared currency = no currency authority).
        approved_currency = (plan.get("commercial") or {}).get("currency")
        if approved_currency:
            for tok in _CURRENCY_RE.findall((text or "").lower()):
                if tok != approved_currency.lower():
                    violations.append(f"wrong_currency:{tok}")
                    break

        # 1c — a T1/T2 estimate must not be worded as a final/fixed quote
        tier = (plan.get("commercial") or {}).get("tier")
        lower = (text or "").lower()
        if tier in ("T1", "T2"):
            for phrase in ("final price", "سعر نهائي", "السعر النهائي",
                           "السعر هو", "confirmed price", "هذا هو السعر"):
                if phrase in lower:
                    violations.append(f"estimate_worded_as_final:{phrase}")
                    break

        # 2 — foreign catalog names + forbidden claims
        lower = (text or "").lower()
        for name in quality.get("forbidden_catalog_names", []):
            if name and name.lower() in lower:
                violations.append(f"foreign_service:{name}")
                break
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in lower:
                violations.append(f"forbidden_claim:{phrase}")
                break

        # 3 — question budget
        q_count = sum(text.count(mark) for mark in _QUESTIONS)
        max_q = int((self.policy.data.get("max_questions_per_reply", 1)
                     if self.policy else 1))
        if q_count > max_q:
            violations.append(f"too_many_questions:{q_count}")

        # 4 — echo / parroting
        if last_customer_text and len(last_customer_text) > 40 \
                and last_customer_text.strip() in (text or ""):
            violations.append("echo_customer")

        # 5 — language (Arabic enforced; others advisory-only today)
        if plan.get("language") == "ar" and text:
            if not _AR_RE.search(text):
                violations.append("language_mismatch:ar")

        # 6 — mode consistency
        if plan.get("mode") != "COMMERCIAL":
            for kw in ("ميزانية", "budget"):
                if kw in lower:
                    violations.append("budget_outside_commercial")
                    break

        # 7 — reask_known (HARD): the plan asks a field already known in the
        #     structured known_facts, without a stated exception (contradiction
        #     or scope change). Deterministic via policy.field_known.
        if not plan.get("allow_reask"):
            q = plan.get("question") or {}
            field = q.get("field") or ""
            if field and field not in ("_opening", "_confirm") \
                    and not str(field).startswith("suggest_"):
                known = plan.get("known_facts") or {}
                if self.policy and self.policy.field_known(field, known):
                    violations.append(f"reask_known:{field}")

        # 8 — repeat_self (ADVISORY only, never a hard block): near-duplicate
        #     of a recent assistant reply. Surfaces as an advisory so the
        #     caller may regenerate; it is not a humanness gate.
        if recent_replies:
            for prior in recent_replies:
                if self._is_repeat(text or "", prior):
                    advisories.append("repeat_self")
                    break

        # 9 — scope_under_review (HARD): a scope expansion is being clarified
        #     (or was not yet captured into the fingerprint inputs). Any figure
        #     in the reply would be a stale/unauthorized number, so a number is
        #     a hard block — a false positive (a needless block) is acceptable,
        #     a false negative (showing a stale price) is forbidden.
        if plan.get("scope_under_review"):
            if _NUM_RE.search(text or ""):
                violations.append("scope_under_review_block:number")

        # 10 — P1-1 §1.3: common brand misspelling in outbound = advisory
        # only (republish phrasing); never a hard block.
        for wrong in ("amancore", "amancor"):
            if wrong in lower:
                advisories.append(f"brand_spelling_advisory:{wrong}")
                break

        return {"allowed": not violations, "violations": violations,
                "advisories": advisories}
