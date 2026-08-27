"""Rolling conversation-summary reducer.

Maintains a compact, deterministic summary of *unstructured conversational
memory* — the deltas a customer actually said across turns — persisted onto the
existing ``ConversationMemory.summary`` field (NO new table, NO schema change).

It stores only deltas:
    * new facts
    * changed scope
    * active objection
    * decision
    * relevant next action

Truth-ordering on any conflict (binding):
    current explicit customer statement
        > structured facts
        > recent context
        > summary

A summary is NEVER a source of truth by itself; it is derived from structured
state at read time and used only as tagged context ("Conversation context:")
for the planner. It is DATA, not instructions.
"""

from __future__ import annotations

SUMMARY_LIMIT = 220


def _first(val):
    if isinstance(val, list) and val:
        return val[-1]
    return val or None


def reduce_memory(mem: dict, limit: int = SUMMARY_LIMIT) -> str:
    """Build a compact rolling summary string from a conversation memory dict.

    Deterministic: given the same structured state it yields the same summary.
    Missing/empty fields are simply omitted; the result is capped at ``limit``.
    """
    facts = (mem or {}).get("facts") or {}
    wm = (mem or {}).get("working_memory") or {}
    parts: list[str] = []

    # new / structured facts (known, non-empty) — the highest signal.
    ordered_keys = ("service_category", "industry", "scope", "key_features",
                    "integrations", "languages", "timeline", "authority",
                    "budget", "problem", "desired_outcome", "users")
    seen: set = set()
    for k in ordered_keys:
        v = facts.get(k) or (wm.get(k) if k in ("service_category", "industry")
                             else None)
        if not v or k in seen:
            continue
        seen.add(k)
        parts.append(f"{k}={str(v)[:40]}")

    # active objection
    obj = _first(mem.get("objections") or [])
    if obj:
        parts.append(f"objection={str(obj)[:40]}")

    # decision
    decision = _first(mem.get("decisions") or [])
    if decision:
        parts.append(f"decision={str(decision)[:40]}")

    # next action
    nxt = (mem or {}).get("next_action") or wm.get("next_action")
    if nxt:
        parts.append(f"next_action={str(nxt)[:40]}")

    if not parts:
        return ""

    summary = " | ".join(parts)
    if len(summary) > limit:
        summary = summary[: limit - 3].rstrip() + "..."
    return summary


def inject_context(mem: dict, limit: int = SUMMARY_LIMIT) -> str:
    """Return the tagged "Conversation context:" line for the planner brief."""
    summary = reduce_memory(mem, limit=limit)
    if not summary:
        return ""
    return f"Conversation context: {summary}"
