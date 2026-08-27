"""Telegram customer channel adapter — official Bot API only.

SEPARATION OF ROLES (critical):
  - OWNER console  : ops/telegram_console.py, env TELEGRAM_BOT_TOKEN/CHAT_ID,
                     long-polling, owner-whitelist enforced.
  - CUSTOMER chan  : THIS adapter, env TELEGRAM_CUSTOMER_BOT_TOKEN +
                     TELEGRAM_CUSTOMER_WEBHOOK_SECRET, webhook-driven,
                     flows through the SAME neutral core as WhatsApp.

The adapter owns: Bot API URLs, token handling, Update parsing, secret-token
webhook validation, chat/update/message identifiers, error taxonomy. The Core
never sees raw Telegram payloads.
"""

from __future__ import annotations

import hmac
import os
import re

from ..ids import new_id, utcnow
from ..log import get_logger
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from .canonical import ChannelCapabilities
from .contract import ChannelAdapter

log = get_logger("channels.telegram")

# Official Bot API single-message cap
TELEGRAM_MAX_TEXT = 4096


class TelegramAPIError(RuntimeError):
    """Raised by the provider boundary; carries classification for retries."""

    def __init__(self, category: str, message: str, http_status: int = 0,
                 retry_after_seconds: int | None = None):
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


_BAD_RECIPIENT_MARKERS = (
    "chat not found", "user deactivated", "bot was blocked",
    "peer id invalid", "chat member not found",
)


def classify_telegram_error(http_status: int, description: str = "",
                            retry_after: int | None = None) -> TelegramAPIError:
    """Official-error-code taxonomy — mirrors wa_errors categories so the
    generic Outbox retry policy applies unchanged:
      auth          401 (or 'Unauthorized')            → dead-letter fast
      bad_recipient 403 blocked / 400 chat-not-found…   → dead-letter fast
      rate_limited  429 (+ parameters.retry_after)      → honor wait
      provider      5xx / unrecognized                  → backoff retries
    """
    desc = (description or "").lower()
    if http_status == 401 or "unauthorized" in desc:
        return TelegramAPIError("auth", f"telegram auth failed ({http_status})",
                                http_status)
    if http_status == 403 or any(m in desc for m in _BAD_RECIPIENT_MARKERS):
        return TelegramAPIError("bad_recipient",
                                f"telegram bad recipient ({http_status}: {desc[:80]})",
                                http_status)
    if http_status == 429:
        return TelegramAPIError("rate_limited", "telegram rate limited (429)",
                                http_status, retry_after_seconds=retry_after)
    if http_status >= 500:
        return TelegramAPIError("provider", f"telegram provider error ({http_status})",
                                http_status)
    return TelegramAPIError("provider", f"telegram send failed ({http_status}: {desc[:80]})",
                            http_status)


class MockTelegramProvider:
    """Deterministic provider for mock/test mode — no external network."""

    def __init__(self):
        self.sent: list[dict] = []
        self.chat_actions: list[dict] = []

    def send(self, recipient: str, payload: dict) -> dict:
        self.sent.append({"recipient": recipient, "payload": payload})
        return {"ok": True, "result": {"message_id": len(self.sent)}}

    def send_chat_action(self, recipient: str, action: str = "typing") -> dict:
        self.chat_actions.append({"recipient": recipient, "action": action})
        return {"ok": True}


class TelegramBotApiProvider:
    """Official Bot API boundary. Production-gated like the Graph provider:

    refuses to send unless production_enabled is explicitly true AND
    mode == 'production'. Credentials alone never unlock external sends.
    """

    def __init__(self, config: dict):
        self.config = config
        self.api_base = str(config.get("api_base", "https://api.telegram.org")).rstrip("/")
        token_env = config.get("bot_token_env", "TELEGRAM_CUSTOMER_BOT_TOKEN")
        self.bot_token = os.environ.get(token_env, "")

    def send(self, recipient: str, payload: dict) -> dict:
        block_unless_production_enabled(self.config)
        if not self.bot_token:
            raise RuntimeError("telegram provider not configured "
                               f"(env '{self.config.get('bot_token_env', 'TELEGRAM_CUSTOMER_BOT_TOKEN')}')")
        url = f"{self.api_base}/bot{self.bot_token}/sendMessage"
        import requests

        try:
            resp = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:  # network → transient
            raise TelegramAPIError("provider", f"telegram network error: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200 or not data.get("ok"):
            params = data.get("parameters") or {}
            raise classify_telegram_error(
                resp.status_code, str(data.get("description", "")),
                params.get("retry_after"))
        result = data.get("result") or {}
        return {"ok": True, "result": {"message_id": result.get("message_id")}}

    def send_chat_action(self, recipient: str, action: str = "typing") -> dict:
        """P1-2 §4 — perceived latency: Telegram typing indicator."""
        block_unless_production_enabled(self.config)
        if not self.bot_token:
            raise RuntimeError("telegram provider not configured "
                               f"(env '{self.config.get('bot_token_env', 'TELEGRAM_CUSTOMER_BOT_TOKEN')}')")
        url = f"{self.api_base}/bot{self.bot_token}/sendChatAction"
        import requests

        try:
            resp = requests.post(url, json={"chat_id": str(recipient),
                                            "action": action}, timeout=10)
        except requests.RequestException as exc:  # network → transient
            raise TelegramAPIError("provider",
                                   f"telegram network error: {exc}") from exc
        if resp.status_code != 200:
            raise classify_telegram_error(resp.status_code,
                                          "sendChatAction failed")
        return {"ok": True}


class TelegramAdapter(ChannelAdapter):
    channel = "telegram"

    def __init__(self, config: dict, provider=None):
        self.config = dict(config or {})
        self.max_text_length = int(self.config.get("max_text_length", TELEGRAM_MAX_TEXT))
        mode = self.config.get("mode", "mock")
        if provider is None:
            provider = MockTelegramProvider() if mode == "mock" \
                else TelegramBotApiProvider(self.config)
        self.provider = provider
        secret = ""
        if self.config.get("signature_required"):
            secret = os.environ.get(
                self.config.get("webhook_secret_env",
                                "TELEGRAM_CUSTOMER_WEBHOOK_SECRET"), "")
        self._webhook_secret = secret

    # ---- contract surface ----------------------------------------------
    def capabilities(self) -> ChannelCapabilities:
        """Smallest production-safe surface: TEXT + reply threading."""
        return ChannelCapabilities(text=True, reply_context=True)

    def signature_header_name(self) -> str:
        """Official secret-token header (setWebhook secret_token)."""
        return "x-telegram-bot-api-secret-token"

    def normalize_recipient(self, raw) -> str:
        """Telegram addressing: numeric chat id (negative for groups).
        Deliberately NOT E.164 — WhatsApp normalization stays independent."""
        s = str(raw or "").strip()
        if not re.fullmatch(r"-?\d+", s):
            raise ValueError(f"invalid telegram chat id: {raw!r}")
        return s

    def send_chat_action(self, recipient: str, action: str = "typing") -> bool:
        """P1-2 §4 — perceived latency hook (delegates to the provider).

        Returns False silently when the provider cannot express chat actions
        (e.g. test doubles) — typing must never break message intake.
        """
        provider = getattr(self.provider, "send_chat_action", None)
        if provider is None:
            return False
        try:
            provider(str(recipient), action)
            return True
        except Exception:  # noqa: BLE001 — indicator is best-effort only
            return False

    def verify_webhook(self, mode: str = "", token: str = "", challenge: str = "") -> dict:
        """Telegram performs NO GET challenge handshake (Meta-style); every
        update POST is authenticated via the secret-token header instead.
        Fail closed on the legacy handshake shape."""
        return {"verified": False,
                "error": "telegram validates updates via "
                         f"{self.signature_header_name()} header, no GET handshake"}

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        """Constant-time compare of the secret-token header. Fail-closed:
        unset secret rejects everything (loud misconfiguration > silent bypass)."""
        if not self._webhook_secret or not signature_header:
            return False
        return hmac.compare_digest(str(signature_header).strip(),
                                   self._webhook_secret)

    def health_probe(self) -> str:
        """Per-channel health check (adapter-owned truth)."""
        mode = self.config.get("mode", "mock")
        if mode == "mock":
            return "mock telegram adapter available (customer messaging " \
                   f"{'ENABLED' if self.config.get('customer_messaging') else 'disabled'})"
        token_env = self.config.get("bot_token_env", "TELEGRAM_CUSTOMER_BOT_TOKEN")
        problems = []
        if not os.environ.get(token_env, ""):
            problems.append(f"missing env {token_env}")
        if self.config.get("signature_required") and not self._webhook_secret:
            problems.append(f"missing env {self.config.get('webhook_secret_env', 'TELEGRAM_CUSTOMER_WEBHOOK_SECRET')}")
        if problems:
            raise RuntimeError("; ".join(problems))
        return "telegram production config verified (token+secret present)"

    # ---- inbound --------------------------------------------------------
    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        """One official Update per POST → zero or one CanonicalEvent.
        Non-message updates (edits, callbacks…) and malformed shapes are
        ignored (logged) — never crash the intake."""
        if not isinstance(body, dict):
            log.warning("telegram webhook rejected: non-object body")
            return []
        update_id = body.get("update_id")
        msg = body.get("message")
        if not isinstance(update_id, int) or not isinstance(msg, dict):
            log.warning("telegram webhook rejected: malformed update")
            return []
        sender = msg.get("from") or {}
        chat = msg.get("chat") or {}
        uid, cid = sender.get("id"), chat.get("id")
        if not isinstance(uid, int) or not isinstance(cid, int):
            log.warning("telegram webhook rejected: missing user/chat ids")
            return []
        text = str(msg.get("text") or "")
        reply_to = msg.get("reply_to_message") or {}
        name = " ".join(x for x in (sender.get("first_name", ""),
                                    sender.get("last_name", "")) if x).strip()
        return [CanonicalEvent(
            event_id=new_id(),
            event_type="message.received",
            timestamp=utcnow(),
            source="telegram",
            channel="telegram",
            actor_type="external",
            actor_id=str(uid),
            idempotency_key=f"tg:{update_id}",
            risk_level="low",
            payload={
                "external_user_id": str(uid),
                "external_conversation_id": str(cid),
                "name": name,
                "message_type": "text" if text else "unsupported",
                "text": text,
                "timestamp": msg.get("date"),
                "reply_to_external_message_id":
                    str(reply_to["message_id"]) if reply_to.get("message_id") else None,
            },
            metadata={
                "provider_message_id": str(msg.get("message_id", new_id())),
                "update_id": update_id,
                "chat_id": str(cid),
            },
        )]

    # ---- outbound -------------------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        if message_type != "text":
            # worker's capability gate should prevent this; belt-and-braces
            raise TelegramAPIError("bad_request",
                                   f"telegram cannot carry '{message_type}'")
        body = payload if isinstance(payload, str) else (payload or {}).get("body", "")
        chat_id = self.normalize_recipient(recipient)
        api_payload: dict = {
            "chat_id": chat_id,
            "text": str(body)[:self.max_text_length],
        }
        reply_to = (payload or {}).get("_reply_to") if isinstance(payload, dict) else None
        if reply_to:
            api_payload["reply_parameters"] = {"message_id": int(reply_to)}
        result = self.provider.send(chat_id, api_payload)
        mid = (result.get("result") or {}).get("message_id")
        return {"provider_message_id": str(mid) if mid is not None else f"tg-{new_id()}",
                "status": "sent"}

    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        if isinstance(exc, TelegramAPIError):
            return exc.category, exc.retry_after_seconds
        return None, None
