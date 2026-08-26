"""WhatsApp Cloud API adapter — official API only (no WAHA/browser automation).

Mock mode is the default; production is gated by explicit configuration.
"""

from __future__ import annotations

import os

import requests

from ..ids import new_id, utcnow
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from .contract import ChannelAdapter
from .verification import WebhookVerifier


class WhatsAppProvider:
    def send(self, recipient: str, message_type: str, payload) -> dict:
        raise NotImplementedError

    def send_raw(self, body: dict) -> dict:
        """Send a pre-built official payload verbatim. Default: unsupported."""
        raise NotImplementedError


class MockWhatsAppProvider:
    """Deterministic provider for mock/test mode — no external network."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, recipient: str, message_type: str, payload) -> dict:
        self.sent.append({"to": recipient, "type": message_type, "payload": payload})
        return {"provider_message_id": f"mock-{new_id()}", "status": "sent"}

    def send_raw(self, body: dict) -> dict:
        self.sent.append({"to": body.get("to"), "type": body.get("type", "raw"), "payload": body})
        return {"provider_message_id": f"mock-{new_id()}", "status": "sent"}


class GraphWhatsAppProvider:
    """Official WhatsApp Cloud API provider (Graph API). Config-driven version.

    SAFETY: refuses to send unless production_enabled is explicitly true AND
    mode == 'production'. Credentials alone never unlock external sends.
    """

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("base_url", "https://graph.facebook.com").rstrip("/")
        self.version = config.get("api_version", "v24.0")
        self.phone_number_id = config.get("phone_number_id")
        self.access_token = os.environ.get(config.get("access_token_env", "WHATSAPP_ACCESS_TOKEN"), "")

    MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")

    def upload_media(self, data: bytes, mime: str, filename: str = "file") -> str:
        """Upload media to Cloud API; returns media_id. Gated like sends."""
        block_unless_production_enabled(self.config)
        if not (self.phone_number_id and self.access_token):
            raise RuntimeError("whatsapp provider not configured (phone_number_id/access_token)")
        url = f"{self.base_url}/{self.version}/{self.phone_number_id}/media"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            files={"file": (filename, data, mime)},
            data={"messaging_product": "whatsapp", "type": mime},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"whatsapp media upload failed: {resp.status_code} {resp.text[:200]}")
        return resp.json()["id"]

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media bytes by id; returns (data, mime). Read-only, ungated."""
        if not self.access_token:
            raise RuntimeError("whatsapp provider not configured (access_token)")
        url = f"{self.base_url}/{self.version}/{media_id}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"whatsapp media lookup failed: {resp.status_code}")
        dl_url = resp.json().get("url")
        if not dl_url:
            raise RuntimeError("whatsapp media url missing")
        dl = requests.get(dl_url, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=120)
        if dl.status_code != 200:
            raise RuntimeError(f"whatsapp media download failed: {dl.status_code}")
        return dl.content, dl.headers.get("Content-Type", "application/octet-stream")

    def send(self, recipient: str, message_type: str, payload) -> dict:
        block_unless_production_enabled(self.config)
        if not (self.phone_number_id and self.access_token):
            raise RuntimeError("whatsapp provider not configured (phone_number_id/access_token)")
        url = f"{self.base_url}/{self.version}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        body = {"messaging_product": "whatsapp", "to": recipient}
        if isinstance(payload, dict) and payload.get("_reply_to"):
            body["context"] = {"message_id": payload.pop("_reply_to")}
        if message_type == "template":
            body["type"] = "template"
            body["template"] = payload  # {name, language:{code}, components:[]}
        elif message_type in self.MEDIA_TYPES and isinstance(payload, dict):
            # {id|link, caption?, filename?} — official media message shape
            body["type"] = message_type
            section = {}
            if payload.get("id"):
                section["id"] = payload["id"]
            elif payload.get("link"):
                section["link"] = payload["link"]
            else:
                raise RuntimeError("media payload requires id or link")
            for k in ("caption", "filename"):
                if payload.get(k):
                    section[k] = payload[k]
            body[message_type] = section
        else:
            text_body = payload if isinstance(payload, str) else payload.get("body", "")
            # W4: hard WhatsApp cap — clamp at the single choke point
            body["type"] = "text"
            body["text"] = {"body": str(text_body)[:4096]}
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        if resp.status_code != 200:
            from .wa_errors import classify_graph_error

            raise classify_graph_error(resp.status_code, resp.text[:500],
                                       resp.headers.get("Retry-After"))
        data = resp.json()
        return {"provider_message_id": data.get("messages", [{}])[0].get("id"), "status": "sent"}

    def send_raw(self, body: dict) -> dict:
        """Reactions / read receipts / any official pre-built payload."""
        block_unless_production_enabled(self.config)
        if not (self.phone_number_id and self.access_token):
            raise RuntimeError("whatsapp provider not configured (phone_number_id/access_token)")
        url = f"{self.base_url}/{self.version}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        if resp.status_code != 200:
            from .wa_errors import classify_graph_error

            raise classify_graph_error(resp.status_code, resp.text[:500],
                                       resp.headers.get("Retry-After"))
        return {"delivered": True}


class WhatsAppAdapter(ChannelAdapter):
    channel = "whatsapp"

    def __init__(self, config: dict, verifier: WebhookVerifier | None = None, provider: WhatsAppProvider | None = None):
        self.config = config
        self.verifier = verifier or WebhookVerifier(
            os.environ.get(config.get("verify_token_env", "WHATSAPP_VERIFY_TOKEN"), ""),
            os.environ.get(config.get("app_secret_env", "WHATSAPP_APP_SECRET"), ""),
        )
        mode = config.get("mode", "mock")
        if provider is None:
            provider = MockWhatsAppProvider() if mode == "mock" else GraphWhatsAppProvider(config)
        self.provider = provider

    # ---- webhook ------------------------------------------------------
    def verify_webhook(self, mode: str, token: str, challenge: str) -> dict:
        return self.verifier.verify(mode, token, challenge)

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        return self.verifier.verify_signature(body_bytes, signature_header)

    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        if not isinstance(body, dict) or body.get("object") != "whatsapp_business_account":
            return []
        events: list[CanonicalEvent] = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    events.append(self._inbound(msg, contacts))
                for status in value.get("statuses", []):
                    events.append(self._status(status))
        return events

    def _inbound(self, msg: dict, contacts: dict) -> CanonicalEvent:
        wa_id = msg.get("from", "")
        msg_id = msg.get("id", new_id())
        msg_type = msg.get("type", "text")
        if msg_type == "reaction":
            r = msg.get("reaction", {})
            return CanonicalEvent(
                event_id=new_id(),
                event_type="message.reaction",
                timestamp=utcnow(),
                source="whatsapp",
                channel="whatsapp",
                actor_type="external",
                actor_id=wa_id,
                idempotency_key=f"wa-react:{msg_id}",
                risk_level="low",
                payload={
                    "external_user_id": wa_id,
                    "target_external_message_id": r.get("message_id", ""),
                    "emoji": r.get("emoji", ""),
                },
                metadata={"provider_message_id": msg_id},
            )
        text = ""
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type in ("image", "document", "audio", "video"):
            text = msg.get(msg_type, {}).get("caption", "") or ""
        return CanonicalEvent(
            event_id=new_id(),
            event_type="message.received",
            timestamp=utcnow(),
            source="whatsapp",
            channel="whatsapp",
            actor_type="external",
            actor_id=wa_id,
            idempotency_key=f"wa:{msg_id}",
            risk_level="low",
            payload={
                "external_user_id": wa_id,
                "name": contacts.get(wa_id, ""),
                "message_type": msg_type,
                "text": text,
                "timestamp": msg.get("timestamp"),
                "reply_to_external_message_id": (msg.get("context") or {}).get("id", "") or None,
            },
            metadata={"provider_message_id": msg_id},
        )

    def _status(self, status: dict) -> CanonicalEvent:
        stype = status.get("status", "delivered")
        return CanonicalEvent(
            event_id=new_id(),
            event_type=f"message.{stype}",
            timestamp=utcnow(),
            source="whatsapp",
            channel="whatsapp",
            actor_type="external",
            actor_id=status.get("recipient_id"),
            idempotency_key=f"wa-status:{status.get('id', new_id())}",
            risk_level="low",
            payload={
                "status": stype,
                "external_message_id": status.get("id"),
                "recipient_external_user_id": status.get("recipient_id"),
            },
        )

    # ---- contract surface ----------------------------------------------
    def capabilities(self):
        from .canonical import ChannelCapabilities

        return ChannelCapabilities(
            text=True, image=True, audio=True, video=True, document=True,
            sticker=True, template=True, reaction=True, read_receipt=True,
            reply_context=True,
        )

    def normalize_recipient(self, raw) -> str:
        from .wa_errors import normalize_e164_digits

        return normalize_e164_digits(str(raw or ""))

    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        from .wa_errors import WhatsAppSendError

        if isinstance(exc, WhatsAppSendError):
            return exc.category, exc.retry_after_seconds
        return None, None

    # ---- send ---------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        return self.provider.send(recipient, message_type, payload)

    def react(self, recipient: str, message_id: str, emoji: str) -> dict:
        """Official reaction payload; empty emoji removes the reaction."""
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "reaction",
            "reaction": {"message_id": message_id, "emoji": emoji},
        }
        return self.provider.send_raw(body)

    def mark_read(self, message_id: str) -> dict:
        """Send read receipt for an inbound customer message."""
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return self.provider.send_raw(body)
