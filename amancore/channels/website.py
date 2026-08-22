"""Website lead intake — public API boundary (backend only, no frontend)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..storage.db import Database

ALLOWED_FIELDS = [
    "name", "company", "email", "phone", "country", "language",
    "industry", "service_interest", "message", "consent", "source", "campaign",
]


class WebsiteLeadIntake:
    def __init__(self, crm, db: Database, config: dict | None = None, audit=None, dispatcher=None):
        self.crm = crm
        self.db = db
        self.config = config or {}
        self.audit = audit
        self.dispatcher = dispatcher

    def validate(self, payload: dict) -> list[str]:
        errors: list[str] = []
        if not isinstance(payload, dict):
            return ["payload must be an object"]
        email = (payload.get("email") or "").strip()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("invalid email")
        if payload.get("consent") not in (True, 1, "true", "yes", "1"):
            errors.append("consent required for marketing contact")
        for field in ("name", "email"):
            value = (payload.get(field) or "").strip()
            if len(value) > 200:
                errors.append(f"{field} too long")
        return errors

    def sanitize(self, payload: dict) -> dict:
        clean = {}
        for k in ALLOWED_FIELDS:
            v = payload.get(k)
            if isinstance(v, str):
                v = re.sub(r"<[^>]+>", "", v).strip()[:2000]
            clean[k] = v
        return clean

    def _rate_limited(self, ip: str, email: str) -> bool:
        now = datetime.now(timezone.utc)
        cfg = self.config or {}
        per_ip = cfg.get("intake_rate_per_ip_minute", 5)
        per_email = cfg.get("intake_rate_per_email_day", 3)
        window_ip = (now - timedelta(minutes=1)).isoformat()
        window_email = (now - timedelta(days=1)).isoformat()
        if ip:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM intake_events WHERE ip = ? AND created_at >= ?", (ip, window_ip)
            ).fetchone()["c"]
            if n >= per_ip:
                return True
        if email:
            n = self.db.execute(
                "SELECT COUNT(*) AS c FROM intake_events WHERE email = ? AND created_at >= ?", (email, window_email)
            ).fetchone()["c"]
            if n >= per_email:
                return True
        return False

    def submit(self, payload: dict, ip: str = "", idempotency_key: str | None = None) -> dict:
        errors = self.validate(payload)
        if errors:
            return {"status": "rejected", "errors": errors}
        clean = self.sanitize(payload)
        email = (clean.get("email") or "").lower()
        if self._rate_limited(ip, email):
            return {"status": "rejected", "errors": ["rate limited"]}

        lead_id = self.crm.create_lead(
            name=clean.get("name"),
            company=clean.get("company"),
            contact_email=email or None,
            contact_whatsapp=clean.get("phone") or None,
            country=clean.get("country"),
            language=clean.get("language"),
            industry=clean.get("industry"),
            service_interest=clean.get("service_interest"),
            need=clean.get("message") or None,
            source_channel="website",
            source_campaign=clean.get("campaign"),
        )
        self.db.execute(
            "INSERT INTO intake_events (intake_id, ip, email, lead_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id(), ip, email, lead_id, utcnow()),
        )
        self.db.commit()
        if self.dispatcher is not None:
            from ..services.events import CanonicalEvent

            self.dispatcher.publish(
                CanonicalEvent(
                    event_id=new_id(),
                    event_type="website.lead.received",
                    timestamp=utcnow(),
                    source="website",
                    channel="website",
                    actor_type="external",
                    idempotency_key=idempotency_key or f"intake:{email}:{clean.get('source')}",
                    payload={"lead_id": lead_id, "source": clean.get("source"), "campaign": clean.get("campaign")},
                )
            )
        if self.audit is not None:
            self.audit.record(action="website.lead.intake", resource="leads", result=lead_id)
        return {"status": "created", "lead_id": lead_id}
