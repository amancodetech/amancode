"""Compliance kit (post-ban guardrails, 2026-08-24 incident).

Three independent locks on business-initiated WhatsApp traffic:

1. ConsentGate      — no initiation without a recorded customer opt-in.
2. SendValve        — daily caps: warm-up tier ceiling + manual approval top-up
                      (owner approves extra volume via Telegram /approve).
3. TemplateLock     — initiations must use an owner-configured template
                      (empty allowlist ⇒ initiations disabled entirely).

Customer-service REPLIES (responding to inbound within the 24h window) are
exempt from Consent/Template but still bounded by the warm-up ceiling as a
reputation guard.
"""

from __future__ import annotations

import json
import threading

from ..ids import utcnow
from ..log import get_logger

log = get_logger("compliance.guard")


class ConsentGate:
    @staticmethod
    def can_initiate(lead: dict) -> tuple[bool, str]:
        if int(lead.get("opt_out") or 0):
            return False, "opted_out"
        if not (lead.get("consent_at") or "").strip():
            return False, "no_recorded_consent"
        return True, "ok"


class SendValve:
    """Daily send ceilings backed by message_outbox counters.

    - tier ceiling applies to ALL outbound (reputation guard)
    - auto cap applies to business-initiated sends only
    - owner can top-up today via approve_today(extra)
    """

    def __init__(self, db, tiers: list[int] | None = None, tier_index: int = 0,
                 auto_cap: int = 50, channel: str = "whatsapp"):
        # CHANNEL POLICY: caps are enforced PER CHANNEL (legacy default keeps
        # historical whatsapp behavior); global reputation ceiling = per-channel
        # tier ceilings summed by configuration, never by ignoring channels.
        self.channel = (channel or "whatsapp").lower()
        self.db = db
        self.tiers = [int(t) for t in (tiers or [50, 250, 1000])]
        self.tier_index = max(0, min(tier_index, len(self.tiers) - 1))
        self.auto_cap = int(auto_cap)
        self._lock = threading.Lock()
        self._reserved_day = None
        self._reserved = 0          # in-process reservations (pre-send)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS compliance_overrides ("
            " day TEXT PRIMARY KEY, approved_extra INTEGER NOT NULL DEFAULT 0)")

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _today() -> str:
        return utcnow()[:10]

    def _sent_today(self, initiated_only: bool) -> int:
        sql = ("SELECT COUNT(*) c FROM message_outbox WHERE channel=? "
               "AND sent_at IS NOT NULL AND substr(sent_at,1,10)=?")
        if initiated_only:
            sql += " AND initiation='yes'"
        row = self.db.execute(sql, (self.channel, self._today())).fetchone()
        try:
            db_count = row["c"]
        except (KeyError, IndexError):
            db_count = row[0]
        approved = self.approved_extra_today()
        return db_count, approved

    def approved_extra_today(self) -> int:
        try:
            row = self.db.execute(
                "SELECT approved_extra FROM compliance_overrides WHERE day=?",
                (self._today(),)).fetchone()
            v = row["approved_extra"] if row is not None and "approved_extra" in row.keys() else (
                row[0] if row else 0)
            return int(v or 0)
        except Exception:  # noqa: BLE001 — table race on first create
            return 0

    def approve_today(self, extra: int) -> int:
        with self._lock:
            self.db.execute(
                "INSERT INTO compliance_overrides (day, approved_extra) VALUES (?,?) "
                "ON CONFLICT(day) DO UPDATE SET approved_extra=approved_extra+?",
                (self._today(), int(extra), int(extra)))
            self.db.commit()
        log.info("valve.approved day=%s extra=+%d", self._today(), extra)
        return self.approved_extra_today()

    # ---- decisions ------------------------------------------------------
    def check_all_outbound(self, n: int = 1) -> tuple[bool, str]:
        sent, _ = self._sent_today(False)
        ceiling = self.tiers[self.tier_index]
        if sent + n > ceiling:
            return False, f"warmup_tier_cap({ceiling}) reached={sent}"
        return True, "ok"

    def check_initiation(self, n: int = 1) -> tuple[bool, str]:
        self._roll_reservation()
        ok, why = self.check_all_outbound(n)
        if not ok:
            return ok, why
        initiated, approved = self._sent_today(True)
        if initiated + self._reserved + n > self.auto_cap + approved:
            return False, (f"auto_cap({self.auto_cap}+{approved} approved) "
                           f"reached={initiated}+reserved={self._reserved}")
        return True, "ok"

    def _roll_reservation(self):
        today = self._today()
        if self._reserved_day != today:
            self._reserved_day = today
            self._reserved = 0

    def reserve_initiations(self, n: int) -> tuple[int, str]:
        """Reserve up to n slots; returns (granted, reason). Reservations
        count against the cap until real sends replace them (same process,
        same valve instance — build_runtime creates it once)."""
        granted = 0
        why = "ok"
        for _ in range(n):
            ok, why = self.check_initiation(1)
            if not ok:
                break
            self._reserved += 1
            granted += 1
        return granted, why


class TemplateLock:
    """Initiations must use an owner-approved template from config."""

    def __init__(self, templates: dict | None):
        self.templates = dict(templates or {})

    def resolve(self, name: str) -> dict | None:
        t = self.templates.get(name)
        if not t:
            log.warning("template.blocked name=%s (allowlist=%s)",
                        name, sorted(self.templates))
            return None
        return t
