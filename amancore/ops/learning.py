"""Company Learning Journal — the AI learns from every conversation.

After each AI-handled exchange we extract a tiny structured lesson (topic,
objection, new need...) and append it to a JSONL journal. Recent lessons are
injected into future reply drafting so the assistant literally gets smarter
with every customer interaction. Append-only data; core brain stays
owner-controlled (golden rule).
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from pathlib import Path

from ..log import get_logger

log = get_logger("learning")

_JOURNAL = Path(__file__).resolve().parents[1] / "business_brain" / "data" / "learnings.jsonl"
_lock = threading.Lock()


def _flash():
    import yaml

    root = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load(open(root / "configs" / "models.yaml"))
    from ..routing.providers import build_providers

    return build_providers(cfg)["deepseek-v4-flash"]


def record_learning(wa_id: str, customer_msg: str, ai_reply: str) -> dict | None:
    """Extract one lesson from an exchange; append to journal. Never raises."""
    try:
        if not customer_msg.strip() or not ai_reply.strip():
            return None
        r = _flash().complete([
            {"role": "system", "content":
             'Extract ONE learning from this exchange as strict JSON only:\n'
             '{"topic": "<2-4 words>",'
             ' "category": "<sales|pricing|support|offtopic>",'
             ' "objection": "<or empty>",'
             ' "new_need": "<customer need not covered by packages, or empty>"}'},
            {"role": "user", "content":
             f"CUSTOMER: {customer_msg[:400]}\nAI REPLY: {ai_reply[:300]}"},
        ])
        raw = re_search(r"\{.*\}", r.text or "")
        if not raw:
            return None
        lesson = json.loads(raw.replace("{{", "{").replace("}}", "}"))
        lesson["ts"] = utc_iso()
        lesson["wa_id"] = wa_id
        _JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_JOURNAL, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(lesson, ensure_ascii=False) + "\n")
        return lesson
    except Exception as exc:  # noqa: BLE001 — learning must never break serving
        log.error("record_learning failed: %s", exc)
        return None


def recent_learnings_summary(limit: int = 25) -> str:
    """Compact brief of the latest lessons for prompt injection."""
    try:
        if not _JOURNAL.exists():
            return ""
        with _lock:
            lines = _JOURNAL.read_text(encoding="utf-8").strip().splitlines()
        lessons = [json.loads(l) for l in lines[-limit:] if l.strip()]
        if not lessons:
            return ""
        topics = Counter(l.get("topic", "?") for l in lessons)
        objections = [l["objection"] for l in lessons if l.get("objection")]
        needs = [l["new_need"] for l in lessons if l.get("new_need")]
        parts = ["What customers recently asked about: "
                 + ", ".join(f"{t}(x{c})" for t, c in topics.most_common(6)) + "."]
        if objections:
            parts.append("Common objections to handle gently: "
                         + "; ".join(list(dict.fromkeys(objections))[:5]) + ".")
        if needs:
            parts.append("Requested-but-uncovered needs (acknowledge, note team will review): "
                         + "; ".join(list(dict.fromkeys(needs))[:5]) + ".")
        return "\nLEARNINGS FROM PAST CONVERSATIONS:\n" + "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        log.error("summary failed: %s", exc)
        return ""


def stats() -> str:
    """Owner-facing digest for /learned."""
    try:
        if not _JOURNAL.exists():
            return "📚 لا تعلّمات مسجلة بعد — ستتراكم مع كل محادثة."
        with _lock:
            lines = _JOURNAL.read_text(encoding="utf-8").strip().splitlines()
        lessons = [json.loads(l) for l in lines if l.strip()]
        topics = Counter(l.get("topic", "?") for l in lessons)
        cats = Counter(l.get("category", "?") for l in lessons)
        out = [f"📚 تعلمت من {len(lessons)} تبادل حتى الآن:",
               "• أكثر المواضيع: " + ", ".join(f"{t} (x{c})" for t, c in topics.most_common(8))]
        obj = [l["objection"] for l in lessons if l.get("objection")]
        if obj:
            out.append("• اعتراضات متكررة: " + "; ".join(list(dict.fromkeys(obj))[-5:]))
        needs = [l["new_need"] for l in lessons if l.get("new_need")]
        if needs:
            out.append("• احتياجات غير مغطاة (فرص تطوير): " + "; ".join(list(dict.fromkeys(needs))[-5:]))
        out.append("• الفئات: " + ", ".join(f"{k}:{v}" for k, v in cats.most_common()))
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        return f"خطأ في قراءة التعلمات: {exc}"


def re_search(pattern: str, text: str):
    import re
    m = re.search(pattern, text, re.S)
    return m.group(0) if m else None


def utc_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
