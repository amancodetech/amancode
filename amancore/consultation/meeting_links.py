"""Meeting link generator for AmanCode consultations.

Ensures cryptographically secure, unguessable meeting URLs without leaking PII (names, phones, emails).
"""

from __future__ import annotations

import secrets
from ..log import get_logger

log = get_logger("consultation.links")


def generate_meeting_link(meeting_type: str = "GOOGLE_MEET", consultation_id: str | None = None) -> str:
    """Generates a secure meeting link based on meeting type."""
    mt = (meeting_type or "GOOGLE_MEET").upper().strip()
    # Cryptographically secure random token
    secure_token = secrets.token_urlsafe(12)

    if mt in ("JITSI", "VIDEO"):
        url = f"https://meet.jit.si/AmanCode-Consultation-{secure_token}"
    elif mt in ("GOOGLE_MEET", "GMEET", "MEET"):
        part1 = secrets.token_hex(2)
        part2 = secrets.token_hex(2)
        part3 = secrets.token_hex(2)
        url = f"https://meet.google.com/amc-{part1}-{part2}"
    elif mt in ("ZOOM",):
        zoom_id = "".join([str(secrets.randbelow(10)) for _ in range(10)])
        pwd = secrets.token_urlsafe(6)
        url = f"https://zoom.us/j/{zoom_id}?pwd={pwd}"
    elif mt in ("PHONE", "CALL"):
        url = "Phone Consultation (Direct Call)"
    else:
        url = f"https://meet.jit.si/AmanCode-Consultation-{secure_token}"

    log.info("generated secure meeting url for type=%s", mt)
    return url
