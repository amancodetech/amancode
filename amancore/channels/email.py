"""Email channel adapter — AmanCode becomes a real email correspondent.

Outbound: SMTP (reuses SMTP_HOST/PORT/USER/PASSWORD; envelope-from = user).
  - message_type "text": payload str (or {"subject", "body"}) → plain email.
  - message_type "email": payload {"subject", "body", optional "ics",
    optional "ics_filename"} → multipart with calendar attachment.
Inbound: canonical inbound-email JSON (produced by email_poll.py from IMAP,
  or a future inbound-email webhook provider):
  {"emails": [{"from", "subject", "text"|"body", "message_id", "date"}]}
  → CanonicalEvents on channel "email" (idempotency `em:{message_id|hash}`).

Identity: the lowercase email address IS the external_user_id, so the
coordinator/CRM/memory/outbox work unchanged (channel-neutral core).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from ..ids import new_id, utcnow
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from .canonical import ChannelCapabilities
from .contract import ChannelAdapter
from .verification import WebhookVerifier

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY_CHARS = 50_000


def normalize_email(raw: str) -> str:
    """Lowercase + validate. Raises ValueError on invalid addresses."""
    addr = str(raw or "").strip().lower()
    if not _EMAIL_RE.match(addr):
        raise ValueError(f"invalid email address: {raw!r}")
    return addr


class EmailAdapter(ChannelAdapter):
    channel = "email"

    def __init__(self, config: dict | None = None, verifier: WebhookVerifier | None = None):
        self.config = dict(config or {})
        self.verifier = verifier  # optional; IMAP path needs no webhook secret

    # ---- webhook (optional inbound-email provider / tests) ----------------
    def signature_header_name(self) -> str:
        return "x-email-webhook-secret"

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        secret = os.environ.get(
            (self.config.get("webhook_secret_env") or "EMAIL_WEBHOOK_SECRET"), "")
        if not secret:
            return True  # no secret configured → IMAP poll is the live path
        return hmac.compare_digest(str(signature_header or ""), secret)

    def verify_webhook(self, mode: str, token: str, challenge: str) -> dict:
        return {"verified": True, "channel": "email"}

    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        if not isinstance(body, dict):
            return []
        items = body.get("emails")
        if not isinstance(items, list):
            return []
        events: list[CanonicalEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                sender = normalize_email(item.get("from", ""))
            except ValueError:
                continue
            text = str(item.get("text") or item.get("body") or "")[:MAX_BODY_CHARS]
            subject = str(item.get("subject") or "")
            mid = str(item.get("message_id") or "")
            idem_src = mid or f"{sender}|{subject}|{text[:200]}"
            idem = "em:" + (mid if mid else hashlib.sha1(
                idem_src.encode("utf-8")).hexdigest()[:16])
            events.append(CanonicalEvent(
                event_id=new_id(),
                event_type="message.received",
                timestamp=str(item.get("date") or utcnow()),
                source="email",
                channel="email",
                actor_type="external",
                actor_id=sender,
                idempotency_key=idem,
                risk_level="low",
                payload={
                    "external_user_id": sender,
                    "name": str(item.get("name") or ""),
                    "message_type": "text",
                    "text": text,
                    "reply_to_external_message_id": None,
                },
                metadata={
                    "provider_message_id": mid or idem,
                    "subject": subject,
                },
            ))
        return events

    # ---- contract surface -------------------------------------------------
    def capabilities(self):
        return ChannelCapabilities(text=True)

    def normalize_recipient(self, raw) -> str:
        return normalize_email(raw)

    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        msg = str(exc).lower()
        if "auth" in msg or "credential" in msg or "535" in msg:
            return "auth", None
        if "timeout" in msg or "connection" in msg or "refused" in msg:
            return "transient", 60
        return None, None

    # ---- send --------------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        if (self.config.get("mode") or "mock") == "production":
            block_unless_production_enabled(self.config)
        to_addr = normalize_email(recipient)
        subject, body, ics, ics_filename = _coerce_payload(
            message_type, payload, self.config)
        send_email(to_addr, subject, body, ics_content=ics,
                   ics_filename=ics_filename)
        return {"provider_message_id": f"em-{new_id()}", "status": "sent"}


def _coerce_payload(message_type: str, payload, config: dict):
    default_subject = str(config.get("default_subject") or "AmanCode")
    if message_type == "text":
        if isinstance(payload, str):
            return default_subject, payload, None, None
        payload = payload or {}
        return (str(payload.get("subject") or default_subject),
                str(payload.get("body") or payload.get("text") or ""),
                None, None)
    if message_type == "email":
        payload = payload if isinstance(payload, dict) else {"body": payload}
        return (str(payload.get("subject") or default_subject),
                str(payload.get("body") or ""),
                payload.get("ics"), payload.get("ics_filename") or "invite.ics")
    raise ValueError(f"email cannot carry '{message_type}'")


def send_email(to_addr: str, subject: str, body: str, *,
               ics_content: str | bytes | None = None,
               ics_filename: str = "invite.ics",
               from_name: str | None = None) -> dict:
    """Send one plain or calendar-invite email via SMTP. Raises on failure."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    if not (host and user and password):
        raise RuntimeError("email not configured (SMTP_HOST/USER/PASSWORD)")
    sender_name = from_name or os.environ.get("EMAIL_FROM_NAME", "AmanCode")

    if ics_content:
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg.attach(MIMEText(body or "", "plain", "utf-8"))
        part = MIMEBase("text", "calendar", method="REQUEST", name=ics_filename)
        raw = ics_content.encode("utf-8") if isinstance(ics_content, str) else ics_content
        part.set_payload(raw)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=ics_filename)
        part.add_header("Content-Type", 'text/calendar; method=REQUEST; name="%s"' % ics_filename)
        msg.attach(part)
    else:
        msg = MIMEText(body or "", "plain", "utf-8")
    msg["Subject"] = subject or "AmanCode"
    msg["From"] = f"{sender_name} <{user}>"
    msg["To"] = to_addr

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
    return {"delivered": True, "to": to_addr}
