"""WA-302 (W1): Graph API error taxonomy + phone normalization (W2).

Every WhatsApp send failure is classified ONCE into a machine-readable
category that downstream retry policy can act on:
  auth          — token expired/invalid (401 or error code 190)   → dead-letter fast, alert
  bad_recipient — invalid phone / not on WhatsApp (400+131026…)  → dead-letter fast
  rate_limited  — 429                                            → honor Retry-After
  provider      — 5xx / network                                  → normal backoff retries
"""

from __future__ import annotations

import re

RETRYABLE_CATEGORIES = {"rate_limited", "provider"}
FAST_DEAD_CATEGORIES = {"auth", "bad_recipient"}

_BAD_RECIPIENT_CODES = {131026, 131030, 131047, 131049, 470}
_AUTH_CODES = {190}


class WhatsAppSendError(RuntimeError):
    """Raised by the WhatsApp adapter; carries classification for retry policy."""

    def __init__(self, category: str, message: str,
                 http_status: int = 0, graph_code: int | None = None,
                 retry_after_seconds: int | None = None):
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.graph_code = graph_code
        self.retry_after_seconds = retry_after_seconds


def classify_graph_error(http_status: int, body: str = "",
                         retry_after_header: str | None = None) -> WhatsAppSendError:
    """Map a failed Graph response to a typed WhatsAppSendError."""
    code = None
    m = re.search(r'"code"\s*:\s*(\d+)', body or "")
    if m:
        code = int(m.group(1))

    if http_status == 401 or (code in _AUTH_CODES):
        return WhatsAppSendError("auth", f"whatsapp auth failed ({http_status}, code={code})",
                                 http_status, code)

    if http_status == 400 and code is not None and code in _BAD_RECIPIENT_CODES:
        return WhatsAppSendError("bad_recipient",
                                 f"whatsapp bad recipient (code={code})",
                                 http_status, code)

    if http_status == 429:
        wait = _parse_retry_after(retry_after_header)
        return WhatsAppSendError("rate_limited", "whatsapp rate limited (429)",
                                 http_status, code, retry_after_seconds=wait)

    if http_status >= 500:
        return WhatsAppSendError("provider", f"whatsapp provider error ({http_status})",
                                 http_status, code)

    # 4xx we don't recognize: treat as provider-transient EXCEPT known-fast-dead codes
    if code in _BAD_RECIPIENT_CODES:
        return WhatsAppSendError("bad_recipient", f"whatsapp bad recipient (code={code})",
                                 http_status, code)
    return WhatsAppSendError("provider", f"whatsapp send failed ({http_status})",
                             http_status, code)


def _parse_retry_after(header: str | None) -> int | None:
    """Retry-After may be seconds ('30') or HTTP-date; seconds form handled."""
    if not header:
        return None
    try:
        return max(1, int(float(header.strip())))
    except ValueError:
        return None


# ── W2: one normalization for every outbound number ──────────────────────────

def normalize_e164_digits(raw: str) -> str:
    """Digits-only international form for Graph API 'to'.

    Rules: strip every non-digit; a literal '00' international prefix is
    removed; '+' never survives digit-stripping anyway. A lone leading '0'
    (local trunk format) is KEPT as-is — silently guessing a country code
    corrupted real numbers (the old lstrip('0') bug).
    """
    digits = re.sub(r"\D", "", raw or "")
    while digits.startswith("00"):
        digits = digits[2:]
    return digits
