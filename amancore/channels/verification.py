"""Official webhook verification — challenge + signature. No bypass."""

from __future__ import annotations

import hashlib
import hmac


class WebhookVerifier:
    def __init__(self, verify_token: str | None = None, app_secret: str | None = None):
        self.verify_token = verify_token
        self.app_secret = app_secret

    def verify(self, mode: str, token: str, challenge: str) -> dict:
        """Meta webhook verification flow (hub.mode / hub.verify_token / hub.challenge)."""
        if mode == "subscribe" and token and token == self.verify_token and challenge:
            return {"verified": True, "challenge": challenge}
        return {"verified": False, "error": "invalid verification token"}

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        """X-Hub-Signature-256: sha256=<hmac> using the app secret."""
        if not signature_header or not self.app_secret:
            return False
        expected = "sha256=" + hmac.new(
            self.app_secret.encode("utf-8"), body_bytes, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)
