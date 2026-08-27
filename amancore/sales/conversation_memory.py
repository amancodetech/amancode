"""Conversation Memory — persists what is known/unknown about a lead."""

from __future__ import annotations

import copy
import json
import re

from ..ids import utcnow
from ..util import run_json

JSON_FIELDS = ["facts", "preferences", "requirements", "unknowns", "decisions", "open_questions", "objections", "working_memory"]
_DEFAULTS = {
    "facts": {}, "preferences": {}, "requirements": {},
    "unknowns": [], "decisions": [], "open_questions": [], "objections": [],
    "working_memory": {},
}


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(s, default):
    try:
        v = json.loads(s)
        return v if v is not None else default
    except (json.JSONDecodeError, TypeError):
        return default


# Deterministic scope-delta vocabulary (P0.3). Keys map to EXISTING
# scope_fingerprint input fields in pricing.registry._SCOPE_KEYS — no new
# fingerprint inputs are invented. A detected feature only becomes a fact when
# an explicit addition signal is present; a plain mention (e.g. "بأي لغة؟") is
# NOT a delta.
SCOPE_DELTA_MAP: dict[str, tuple[str, ...]] = {
    "booking": ("booking", "reservation", "reserve", "حجز", "احجز", "حجوزات"),
    "payments": ("payment", "checkout", "online order", "ordering", "order online",
                 "دفع", "بوابة دفع", "أوردر", "طلبات أونلاين", "طلب أونلاين", "أونلاين"),
    "integrations": ("integration", "integrate", "sync", "api",
                     "ربط", "تكامل", "اتصال"),
    "languages": ("bilingual", "multilingual", "لغتين", "متعدد اللغات", "عدة لغات"),
    "member_areas": ("portal", "membership", "member area", "بوابة أعضاء",
                     "عضويات", "عضوية", "منطقة الأعضاء"),
    "dynamic_content": ("gallery", "image gallery", "news", "blog", "معرض صور",
                        "معرض", "أخبار", "مدونة", "صور المنتجات"),
}

# Addition signals — the message must carry one for a feature to be a delta.
_SCOPE_ADD_RE = re.compile(
    r"(أضيف|أضِف|أضف|كمان|نضيف|أيضاً|أيضا|زيد|إضافة|إضافة|add|also|plus|and|"
    r"بالإضافة)", re.IGNORECASE)
# Negation within a small window before the feature keyword => NOT a delta.
# Word-boundary anchored so "ما" inside "كمان"/"نظام" is NOT treated as
# negation; a standalone ما/لا/بدون/بلا/دون/without/no/not is.
_SCOPE_NEG_RE = re.compile(
    r"\b(ما|لا|بدون|بلا|دون|without|no|not)\b", re.IGNORECASE)
_NEG_WINDOW = 10


def detect_scope_delta(message: str) -> set[str]:
    """Deterministic scope-delta detector (P0.3 / GAP-1).

    Returns the set of ``_SCOPE_KEYS``-compatible fact fields the customer is
    ADDING to the scope. Only fires when an addition signal co-occurs with a
    feature keyword. A negated mention ("بدون حجز") is not a delta. On any
    ambiguity the safety bias is to treat it as a delta (false positive is
    acceptable; a false negative could leak a stale price).
    """
    msg = (message or "").lower()
    if not msg or not _SCOPE_ADD_RE.search(msg):
        return set()
    found: set[str] = set()
    for field, keywords in SCOPE_DELTA_MAP.items():
        for kw in keywords:
            idx = msg.find(kw.lower())
            if idx == -1:
                continue
            # negation check on the small window right before the keyword
            window = msg[max(0, idx - _NEG_WINDOW):idx]
            if _SCOPE_NEG_RE.search(window):
                break  # negated — not an addition; safety accepts the ambiguity
            found.add(field)
            break
    return found


class ConversationMemory:
    def __init__(self, crm):
        self.crm = crm

    def get_or_create(self, lead_id: str, channel: str = "internal", language: str = "en") -> dict:
        conv = self.crm.get_conversation_for_lead(lead_id)
        if conv is None:
            cid = self.crm.append_conversation(lead_id, channel, language=language, current_state="new")
            conv = self.crm.get_conversation(cid)
        return self.deserialize(conv)

    def deserialize(self, conv: dict) -> dict:
        m = dict(conv)
        for f in JSON_FIELDS:
            m[f] = _loads(m.get(f), copy.deepcopy(_DEFAULTS[f]))
        return m

    def save(self, memory: dict) -> None:
        updates = {f: _dumps(memory.get(f, _DEFAULTS[f])) for f in JSON_FIELDS}
        updates.update({
            "current_state": memory.get("current_state"),
            "summary": memory.get("summary"),
            "last_message_at": memory.get("last_message_at"),
            "next_action": memory.get("next_action"),
            "next_followup_at": memory.get("next_followup_at"),
        })
        self.crm.update_conversation(memory["conversation_id"], **updates)

    def merge_facts(self, memory: dict, new_facts: dict) -> dict:
        for k, v in (new_facts or {}).items():
            if not v:
                continue
            old = memory["facts"].get(k)
            if old and old != v:
                q = f"clarify {k}"
                if q not in memory["open_questions"]:
                    memory["open_questions"].append(q)
            else:
                memory["facts"][k] = v
                memory["open_questions"] = [q for q in memory.get("open_questions", []) if k not in q]
        return memory


def extract_facts(message: str, router=None) -> dict:
    facts = _deterministic_facts(message)
    if router is not None:
        data = run_json(router, "extraction", _FACT_PROMPT.format(message=message))
        if isinstance(data, dict):
            for k, v in data.items():
                if v:
                    facts[k] = v
    return facts


def _deterministic_facts(message: str) -> dict:
    m = message or ""
    facts: dict = {}
    bm = re.search(r"(\$\s?\d[\d,.]*|Rp\s?\d[\d,.]*|IDR\s?\d[\d,.]*|\d[\d,.]*\s?(USD|ريال|درهم|dollar))", m, re.I)
    if bm:
        facts["budget"] = bm.group(0).rstrip(",.")
    elif re.search(r"budget|ميزانية|anggaran", m, re.I):
        facts["budget"] = "mentioned"
    if re.search(r"owner|founder|المالك|صاحب|مدير|decision maker|i am the", m, re.I):
        facts["authority"] = "owner/decision-maker"
    tm = re.search(r"(\d+\s*(week|month|day)s?|asap|urgent|أسبوع|شهر|يوم|قريب|segera)", m, re.I)
    if tm:
        facts["timeline"] = tm.group(0)
    if re.search(r"need|want|looking for|أريد|نحتاج|butuh|mau|cari", m, re.I):
        facts["problem"] = "stated"
    if re.search(r"goal|want to|increase|improve|grow|أريد أن|نزيد|ingin|meningkat", m, re.I):
        facts["desired_outcome"] = "stated"
    # P0.3 / GAP-1 — deterministic scope-delta capture: feed the same fields
    # that drive scope_fingerprint so a genuine scope expansion changes the
    # fingerprint through the EXISTING path (no new inputs invented).
    for field in detect_scope_delta(message):
        facts[field] = True
    return facts


_FACT_PROMPT = """Extract structured facts from this customer message as JSON. Include only non-empty keys:
problem, desired_outcome, current_process, users, scope, timeline, budget, authority,
constraints, integrations, languages, support_needs, decisions (list), objections (list).

Message: {message}
"""
