"""Meta channels — Facebook (Messenger) + Instagram (DM) adapters.

Same Graph-platform webhook mechanics as WhatsApp: GET hub.challenge
handshake + X-Hub-Signature-256 (fail-closed). Messaging starts in mock
mode; production sends are gated exactly like whatsapp/telegram
(block_unless_production_enabled). Echoes, read receipts and delivery
notifications produce ZERO events — only real customer messages do.
"""

from __future__ import annotations

import os

import requests

from ..ids import new_id, utcnow
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from .contract import ChannelAdapter
from .verification import WebhookVerifier


class MockMetaProvider:
    """Deterministic provider for mock/test mode — no external network."""

    def __init__(self, channel: str = "facebook"):
        self.channel = channel
        self.sent: list[dict] = []

    def send(self, recipient: str, message_type: str, payload) -> dict:
        self.sent.append({"to": recipient, "type": message_type,
                          "payload": payload})
        return {"provider_message_id": f"mock-{new_id()}", "status": "sent"}

    def mark_seen(self, recipient: str) -> dict:
        self.sent.append({"to": recipient, "type": "mark_seen"})
        return {"delivered": True}


class GraphMessengerProvider:
    """Official Send API provider. Config-driven; gated like WhatsApp."""

    # Messenger Send API single-message cap for text
    MAX_TEXT = 2000

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("base_url", "https://graph.facebook.com").rstrip("/")
        self.version = config.get("api_version", "v21.0")
        # Messenger sends go to /me/messages with the PAGE token
        self.page_id = config.get("page_id")
        self.access_token = os.environ.get(
            config.get("access_token_env", "META_PAGE_ACCESS_TOKEN"), "")

    def _post(self, body: dict) -> dict:
        block_unless_production_enabled(self.config)
        if not self.access_token:
            raise RuntimeError("meta provider not configured (access token)")
        url = f"{self.base_url}/{self.version}/me/messages"
        resp = requests.post(
            url, params={"access_token": self.access_token},
            json=body, timeout=30)
        if resp.status_code != 200:
            from .wa_errors import classify_graph_error

            raise classify_graph_error(resp.status_code, resp.text[:500],
                                       resp.headers.get("Retry-After"),
                                       label="meta", include_body=True)
        data = resp.json()
        return {"provider_message_id":
                (data.get("message_id") or data.get("recipient_id") or ""),
                "status": "sent"}

    def send(self, recipient: str, message_type: str, payload) -> dict:
        text = payload if isinstance(payload, str) else payload.get("body", "")
        body = {
            "recipient": {"id": recipient},
            "messaging_type": "RESPONSE",
            "message": {"text": str(text)[: self.MAX_TEXT]},
        }
        return self._post(body)


class GraphInstagramProvider(GraphMessengerProvider):
    """Instagram Direct messaging via the IG professional account node."""

    MAX_TEXT = 1000  # Instagram DM text cap

    def __init__(self, config: dict):
        super().__init__(config)
        self.ig_user_id = config.get("ig_user_id")

    def _post(self, body: dict) -> dict:
        block_unless_production_enabled(self.config)
        if not (self.access_token and self.ig_user_id):
            raise RuntimeError("instagram provider not configured "
                               "(ig_user_id/access token)")
        url = f"{self.base_url}/{self.version}/{self.ig_user_id}/messages"
        resp = requests.post(
            url, params={"access_token": self.access_token},
            json=body, timeout=30)
        if resp.status_code != 200:
            from .wa_errors import classify_graph_error

            raise classify_graph_error(resp.status_code, resp.text[:500],
                                       resp.headers.get("Retry-After"),
                                       label="meta", include_body=True)
        data = resp.json()
        entries = ((data.get("recipient_id") and [{"id": data["recipient_id"]}])
                   or data.get("entries") or [{}])
        first = entries[0] if entries else {}
        ids = ((first.get("identities") or [{}])[0].get("id", ""))
        return {"provider_message_id": ids or "", "status": "sent"}


def _meta_verifier(config: dict) -> WebhookVerifier:
    """Shared handshake verifier. App secret falls back to the WHATSAPP one
    because Messenger/IG/WhatsApp live in ONE Meta app (one secret)."""
    secret = (os.environ.get(config.get("app_secret_env", "META_APP_SECRET"), "")
              or os.environ.get("WHATSAPP_APP_SECRET", ""))
    return WebhookVerifier(
        os.environ.get(config.get("verify_token_env", "META_VERIFY_TOKEN"), ""),
        secret,
    )


class MetaAdapterBase(ChannelAdapter):
    """Common webhook parsing for object='page' | 'instagram'.

    Produces CanonicalEvents ONLY for real inbound user messages
    (text or attachment); echoes/receipts/postback-status noise → [].
    Subclasses set channel / obj_name / sender key handling.
    """

    channel = ""
    obj_name = "page"

    #: entry-level messaging items carry events; subclass hook for IG variants
    idempotency_prefix = "fb"
    default_provider_cls = GraphMessengerProvider
    mock_provider_cls = MockMetaProvider

    def __init__(self, config: dict, provider=None):
        self.config = dict(config or {})
        self.verifier = _meta_verifier(self.config)
        mode = self.config.get("mode", "mock")
        if provider is None:
            provider = (self.mock_provider_cls(self.channel)
                        if mode == "mock"
                        else self.default_provider_cls(self.config))
        self.provider = provider

    # ---- webhook ------------------------------------------------------
    def verify_webhook(self, mode: str, token: str, challenge: str) -> dict:
        return self.verifier.verify(mode, token, challenge)

    def verify_signature(self, body_bytes: bytes, signature_header) -> bool:
        return self.verifier.verify_signature(body_bytes, signature_header)

    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        if not isinstance(body, dict) or body.get("object") != self.obj_name:
            return []
        events: list[CanonicalEvent] = []
        for entry in body.get("entry", []):
            for msg in entry.get("messaging", []) or []:
                evt = self._messaging_item(msg)
                if evt is not None:
                    events.append(evt)
        return events

    def _messaging_item(self, msg: dict) -> CanonicalEvent | None:
        message = msg.get("message") or {}
        sender = (msg.get("sender") or {}).get("id", "")
        if not sender:
            return None  # our own outbound/echo has no customer sender here
        if message.get("is_echo"):
            return None  # CRITICAL: never re-process our own outgoing sends
        mid = message.get("mid") or new_id()
        postback = msg.get("postback")
        if not message and postback:
            text = str(postback.get("title") or postback.get("payload") or "")
        else:
            text = str(message.get("text") or "")
            if not text:
                atts = message.get("attachments") or []
                if atts:
                    first = atts[0] or {}
                    kind = first.get("type", "attachment")
                    url = ((first.get("payload") or {}).get("url")) or ""
                    return self._event(sender, mid, "image",
                                       f"[{kind}] {url}".strip(),
                                       message.get("reply_to"))
                return None  # delivery/read receipts etc.
        reply_to = None
        ctx = message.get("reply_to") or {}
        if isinstance(ctx, dict):
            reply_to = ((ctx.get("message") or {}).get("mid")) or None
        return self._event(sender, mid, "text", text, reply_to)

    def _event(self, actor_id: str, mid: str, mtype: str, text: str,
               reply_to=None) -> CanonicalEvent:
        return CanonicalEvent(
            event_id=new_id(),
            event_type="message.received",
            timestamp=utcnow(),
            source=self.channel,
            channel=self.channel,
            actor_type="external",
            actor_id=actor_id,
            idempotency_key=f"{self.idempotency_prefix}:{mid}",
            risk_level="low",
            payload={
                "external_user_id": actor_id,
                "name": "",
                "message_type": mtype,
                "text": text,
                "reply_to_external_message_id": reply_to,
            },
            metadata={"provider_message_id": mid},
        )

    # ---- contract surface ----------------------------------------------
    def capabilities(self):
        from .canonical import ChannelCapabilities

        return ChannelCapabilities(text=True, image=True, audio=False,
                                   video=False, document=False, sticker=False,
                                   template=True, reaction=False,
                                   read_receipt=True, reply_context=False)

    def normalize_recipient(self, raw) -> str:
        import re as _re

        psid = str(raw or "").strip()
        return _re.sub(r"[^A-Za-z0-9_\-]", "", psid)

    def classify_error(self, exc: Exception) -> tuple | tuple[None, None]:
        err = getattr(exc, "category", None), getattr(exc, "retry_after_seconds", None)
        return err if err != (None, None) else (None, None)

    # ---- send ---------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        return self.provider.send(recipient, message_type, payload)


class FacebookAdapter(MetaAdapterBase):
    channel = "facebook"
    obj_name = "page"
    idempotency_prefix = "fb"
    default_provider_cls = GraphMessengerProvider


class InstagramAdapter(MetaAdapterBase):
    channel = "instagram"
    obj_name = "instagram"
    idempotency_prefix = "ig"
    default_provider_cls = GraphInstagramProvider
