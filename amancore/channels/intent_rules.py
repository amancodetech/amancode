"""Structured approval-intent classification (AI-104 — fixes audit C6).

Replaces the fragile substring regex that read «لست موافق» as approval.
Pure function, deterministic, no LLM. Four outcomes:

    AFFIRMATIVE   explicit consent      → may trigger human handover
    NEGATIVE      refusal               → must NEVER trigger handover
    UNCERTAIN     ack / unclear / echo-question
    HUMAN_REQUEST caller wants a person → routed by caller

Decision order: human_request → negated-strong scan → bare negator
→ unnegated strong → weak-ack → uncertain.
"""

from __future__ import annotations

import re

AFFIRMATIVE = "affirmative"
NEGATIVE = "negative"
UNCERTAIN = "uncertain"
HUMAN_REQUEST = "human_request"

_TATWEEL = "\u0640"
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670]")

_NEGATORS = {"لا", "لست", "ليس", "مش", "مو", "ما", "غير",
             "not", "no", "never", "dont", "don t", "tidak", "degil"}

_STRONG = {"موافق", "أوافق", "اوافق", "وافق", "متفق", "نوافق", "استصدرت",
           "نعم", "اي", "yes", "approved", "agree", "agreed", "approval"}

_WEAK = {"اوكي", "أوكي", "اوك", "أوك", "oki", "ok", "okay", "تمام",
         "حسنا", "حسناً", "ايوا", "أيوه", "ايه", "طيب", "yep", "yeah"}

_THANKS = {"شكرا", "شكراً", "تسلم", "يعطيك", "thanks", "thank", "thx"}

_HUMAN = re.compile(
    r"(human|real\s*person|talk\s*to\s*(owner|someone|person)|speak.*person|"
    r"[إا]نسان|بشري|صاحب|موظف|شخص|orang|manusia)",
    re.IGNORECASE,
)

_SPLIT = re.compile(r"[\s،,.؛;:!؟?\n\r]+")


def _normalize(text: str) -> str:
    t = (text or "").strip()
    t = t.replace(_TATWEEL, "")
    t = _DIACRITICS.sub("", t)
    return t.lower()


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(_normalize(text)) if t]


def classify_approval(text: str, prev_out: str = "") -> str:
    """Classify the customer reply at an approval checkpoint."""
    raw = text or ""
    normalized = _normalize(raw)
    if not normalized:
        return UNCERTAIN

    if _HUMAN.search(raw):
        return HUMAN_REQUEST

    tokens = _tokens(raw)
    lower_words = set(tokens)

    has_negator = bool(lower_words & _NEGATORS)
    first_negator = next((i for i, t in enumerate(tokens) if t in _NEGATORS), None)
    strong_before_negator = [
        (i, tok) for i, tok in enumerate(tokens)
        if tok in _STRONG and (first_negator is None or i < first_negator)
    ]

    if strong_before_negator:
        intent = AFFIRMATIVE
        # echo-question: bare «موافق؟» repeats our question, not consent
        if raw.rstrip().endswith(("?", "؟")) and len(tokens) <= 2 \
                and not any(w in _THANKS for w in lower_words):
            intent = UNCERTAIN
        return intent

    if has_negator:
        # any strong term appearing AFTER a negation is consumed by it,
        # and bare negators are refusals — C6 safety bias (never false-approve)
        return NEGATIVE

    if lower_words & _WEAK:
        # weak acks («أوكي», «تمام») and polite closers are never consent
        return UNCERTAIN

    return UNCERTAIN


def summary_question_pending(prev_out: str) -> bool:
    """True when the previous outbound message ended with the approval ask."""
    if not prev_out:
        return False
    flat = _normalize(prev_out)
    return "هل انت موافق" in flat or "موافق؟" in flat or "هل هذا صحيح" in flat
