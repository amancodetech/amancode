"""IMAP inbox poller — inbound email leg of the email channel.

Strategy (safe by construction):
- Fetches UNSEEN messages only (cap per poll), converts each to the
  canonical inbound-email JSON shape, and returns it for
  `coordinator.handle_inbound("email", body)`.
- Marks a message \\Seen ONLY after handle_inbound accepts it, so a crash
  re-delivers instead of losing mail. Residual duplicates are absorbed by
  the coordinator's Message-ID idempotency keys (`em:{message_id}`).

Auth: EMAIL_IMAP_HOST/USER/PASSWORD/MAILBOX. USER/PASSWORD fall back to
SMTP_USER/SMTP_PASSWORD (Gmail app-password reuse). NOTE: the Gmail app
password previously lived in transcripts — rotate it in Google Account →
Security → App passwords if it was ever shared.
"""

from __future__ import annotations

import email as _email
import email.header
import email.utils
import os
from email.message import Message

from ..log import get_logger

log = get_logger("channels.email_poll")

MAX_PER_POLL = 20
MAX_BODY_CHARS = 50_000


def _cfg(name: str, default: str = "") -> str:
    return str(os.environ.get(name, "") or default)


def _decode_header(value) -> str:
    try:
        parts = _email.header.decode_header(value or "")
        out = []
        for chunk, charset in parts:
            if isinstance(chunk, bytes):
                out.append(chunk.decode(charset or "utf-8", errors="replace"))
            else:
                out.append(chunk)
        return "".join(out)
    except Exception:  # noqa: BLE001 — never break a poll on odd headers
        return str(value or "")


def _body_of(msg: Message) -> str:
    """First text/plain part (walk multiparts); notes attachment presence."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                disp = str(part.get("Content-Disposition") or "")
                ctype = str(part.get_content_type() or "")
                if ctype == "text/plain" and "attachment" not in disp:
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")[:MAX_BODY_CHARS]
            return "[email with attachment(s), no plain-text body]"
        payload = msg.get_payload(decode=True)
        if payload is None:
            return str(msg.get_payload() or "")[:MAX_BODY_CHARS]
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")[:MAX_BODY_CHARS]
    except Exception:  # noqa: BLE001
        return ""


def parse_message(raw: bytes) -> dict | None:
    """Parse one RFC822 blob → inbound-email item (or None to skip)."""
    try:
        msg = _email.message_from_bytes(raw)
        sender = _email.utils.parseaddr(str(msg.get("From") or ""))[1].strip().lower()
        if not sender or "@" not in sender:
            return None
        return {
            "from": sender,
            "name": _email.utils.parseaddr(str(msg.get("From") or ""))[0],
            "subject": _decode_header(msg.get("Subject")),
            "text": _body_of(msg),
            "message_id": str(msg.get("Message-ID") or "").strip("<> "),
            "date": str(msg.get("Date") or ""),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("skipping unparsable email: %s", exc)
        return None


def poll_inbox_once(limit: int = MAX_PER_POLL) -> dict:
    """Fetch UNSEEN mail → {"emails": [...], "uids": [...]}. No state change
    here: the caller marks UIDs Seen after successful intake."""
    import imaplib

    host = _cfg("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(_cfg("EMAIL_IMAP_PORT", "993") or 993)
    user = _cfg("EMAIL_IMAP_USER") or _cfg("SMTP_USER")
    password = _cfg("EMAIL_IMAP_PASSWORD") or _cfg("SMTP_PASSWORD")
    mailbox = _cfg("EMAIL_IMAP_MAILBOX", "INBOX")
    if not (host and user and password):
        raise RuntimeError("inbound email not configured (EMAIL_IMAP_HOST/USER/PASSWORD)")

    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, password)
        typ, _ = conn.select(mailbox, readonly=False)
        if typ != "OK":
            raise RuntimeError(f"cannot select mailbox {mailbox!r}")
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            return {"emails": [], "uids": []}
        uids = [u for u in (data[0] or b"").split() if u][: max(1, limit)]
        emails, ok_uids = [], []
        for uid in uids:
            try:
                typ, fetched = conn.fetch(uid, "(RFC822)")
                if typ != "OK" or not fetched or not fetched[0]:
                    continue
                item = parse_message(fetched[0][1])
                if item and item.get("text") is not None:
                    emails.append(item)
                    ok_uids.append(uid)
            except Exception as exc:  # noqa: BLE001 — one bad mail never stops the poll
                log.warning("fetch failed for uid %s: %s", uid, exc)
        return {"emails": emails, "uids": ok_uids}
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def mark_seen(uids: list) -> None:
    """Flag successfully-ingested UIDs \\Seen (best-effort, own connection)."""
    if not uids:
        return
    import imaplib

    host = _cfg("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(_cfg("EMAIL_IMAP_PORT", "993") or 993)
    user = _cfg("EMAIL_IMAP_USER") or _cfg("SMTP_USER")
    password = _cfg("EMAIL_IMAP_PASSWORD") or _cfg("SMTP_PASSWORD")
    mailbox = _cfg("EMAIL_IMAP_MAILBOX", "INBOX")
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(user, password)
            conn.select(mailbox)
            for uid in uids:
                try:
                    conn.store(uid, "+FLAGS", "\\Seen")
                except Exception:  # noqa: BLE001
                    pass
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001 — Seen-flagging never breaks intake
        log.warning("mark_seen failed: %s", exc)
