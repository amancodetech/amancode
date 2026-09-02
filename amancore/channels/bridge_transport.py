"""BridgeTransport — the ONLY way AmanCode talks to the local meta-bridge.

Owner spec §9/§10/§13/§15/§43/§44:
  - local HTTP only (127.0.0.1:8765 default), X-Bridge-Token auth
  - connect timeout + read timeout, small bounded retries for CONNECT errors
    ONLY (the request provably never reached the bridge)
  - a READ timeout after a send request left the process is DELIVERY_UNKNOWN —
    it maps to the existing outbox `uncertain` state, NEVER a blind retry
  - structured error taxonomy shared with the outbox classifier
  - shadow mode: flagged per request so the bridge performs every real step
    (validation, session check, normalization) but does not deliver
"""

from __future__ import annotations

import os
import time
from urllib.parse import quote

import requests

from ..log import get_logger

log = get_logger("channels.bridge_transport")

# Bridge error taxonomy (owner spec §43) — mapped onto the outbox classifier:
#   auth / bad_recipient → fast dead · rate_limited / temporary → retryable
#   delivery_unknown → outbox `uncertain` (never retried blindly)
CATEGORIES = ("auth_required", "rate_limited", "temporary", "invalid_request",
              "not_found", "delivery_unknown", "permanent")


class BridgeError(RuntimeError):
    """Raised for any classified bridge/transport failure."""

    def __init__(self, category: str, message: str, *,
                 http_status: int = 0, retry_after_seconds: int | None = None,
                 error_code: str | None = None):
        if category not in CATEGORIES:
            raise ValueError(f"unknown bridge error category: {category}")
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.error_code = error_code or category.upper()


class BridgeTransport:
    """Synchronous local HTTP client for one channel's bridge transport."""

    def __init__(self, config: dict):
        bridge = dict((config or {}).get("bridge") or {})
        self.channel = str((config or {}).get("channel", "whatsapp"))
        self.base_url = str(bridge.get("base_url", "http://127.0.0.1:8765")).rstrip("/")
        self.token_env = str(bridge.get("token_env", "AMANCODE_BRIDGE_TOKEN"))
        self.token = os.environ.get(self.token_env, "")
        self.shadow = bool(bridge.get("shadow", False))
        self.connect_timeout = float(bridge.get("connect_timeout", 3.0))
        self.read_timeout = float(bridge.get("read_timeout", 30.0))
        self.connect_retries = max(0, int(bridge.get("connect_retries", 2)))

    # ---- request core ---------------------------------------------------
    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Bridge-Token"] = self.token
        for k, v in (extra or {}).items():
            headers[k] = v
        return headers

    def _classify_http(self, status: int, body: str,
                       retry_after: str | None) -> BridgeError:
        detail = (body or "")[:160].replace("\n", " ")
        if status in (401, 403):
            return BridgeError("auth_required",
                               f"bridge auth failed ({status}): {detail}",
                               http_status=status)
        if status == 404:
            return BridgeError("not_found", f"bridge not found: {detail}",
                               http_status=status)
        if status == 429:
            wait = None
            try:
                wait = max(1, int(float((retry_after or "").strip())))
            except ValueError:
                pass
            return BridgeError("rate_limited", "bridge rate limited (429)",
                               http_status=status, retry_after_seconds=wait)
        if status == 400:
            return BridgeError("invalid_request",
                               f"bridge rejected request (400): {detail}",
                               http_status=status)
        if status >= 500:
            return BridgeError("temporary", f"bridge error ({status}): {detail}",
                               http_status=status)
        return BridgeError("permanent", f"bridge unexpected status ({status}): {detail}",
                           http_status=status)

    def request(self, method: str, path: str, *,
                json_body: dict | None = None,
                uncertainty: str = "temporary",
                timeout: float | None = None,
                raw_response: bool = False) -> dict | bytes:
        """One authenticated bridge request.

        uncertainty: what a READ timeout means for THIS call —
          "delivery_unknown" for send-style requests (the request may have
          reached the platform) or "temporary" for probes/status reads.
        """
        url = self.base_url + path
        timeout = timeout or (self.connect_timeout, self.read_timeout)
        attempts = self.connect_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = requests.request(method, url, json=json_body,
                                        headers=self._headers(), timeout=timeout)
                break
            except requests.exceptions.ConnectTimeout as exc:
                last_exc = exc          # request never left — retryable
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc          # bridge down — retryable
            except requests.exceptions.ReadTimeout as exc:
                # the request WAS sent; never blind-retry (owner spec §44)
                if uncertainty == "delivery_unknown":
                    raise BridgeError(
                        "delivery_unknown",
                        f"bridge send timeout — delivery state unknown") from exc
                raise BridgeError(
                    "temporary", f"bridge timeout on {method} {path}") from exc
            if attempt < attempts:
                time.sleep(0.4 * attempt)
                log.info("bridge.connect_retry attempt=%d method=%s path=%s",
                         attempt, method, path)
        else:
            raise BridgeError("temporary",
                              f"bridge unreachable after {attempts} attempts "
                              f"({self.base_url}): {last_exc}")
        if resp.status_code >= 400:
            raise self._classify_http(resp.status_code, resp.text,
                                      resp.headers.get("Retry-After"))
        if raw_response:
            return resp.content
        try:
            return resp.json()
        except ValueError as exc:
            raise BridgeError("permanent",
                              f"bridge returned non-JSON for {path}") from exc

    # ---- typed surface ---------------------------------------------------
    @staticmethod
    def _channel_path(channel: str) -> str:
        return quote(str(channel or "whatsapp"), safe="")

    def send_message(self, channel: str, message: dict) -> dict:
        """Send one message through the bridge. Delivery-uncertainty aware."""
        # The bridge server reads `body.to` for the recipient phone number,
        # so lift it out of the message dict into the top-level body.
        recipient = message.pop("recipient", None) or ""
        body = {"channel": channel, "shadow": self.shadow,
                "to": recipient, "message": message}
        result = self.request("POST", "/v1/messages/send", json_body=body,
                              uncertainty="delivery_unknown")
        if not isinstance(result, dict):
            raise BridgeError("permanent", f"bridge send refused: {result!r}"[:200])
        # The bridge returns {message_id, to, would_send?, shadow?} on success.
        # A missing message_id on a non-shadow send is still valid (delivery_unknown
        # semantics); only a hard refusal (empty dict / explicit error) is fatal.
        if result.get("error"):
            raise BridgeError("temporary",
                              f"bridge send error: {result['error']}"[:200])
        return {
            "external_message_id": (result.get("external_message_id")
                                    or result.get("message_id") or ""),
            "status": "sent",
            "would_send": result.get("would_send", False),
            "accepted": True,
        }

    def upload_media(self, data: bytes, mime: str, filename: str = "file",
                     channel: str | None = None) -> str:
        result = self.request(
            "POST", f"/v1/messages/media",
            json_body={"channel": channel or self.channel, "mime": mime,
                       "filename": filename,
                       "data_base64": __import__("base64").b64encode(data).decode()},
            uncertainty="temporary", timeout=(self.connect_timeout, 120.0))
        media_id = (result or {}).get("media_id")
        if not media_id:
            raise BridgeError("permanent", "bridge media upload returned no id")
        return str(media_id)

    def download_media(self, media_id: str, channel: str | None = None) -> tuple[bytes, str]:
        content = self.request(
            "GET", f"/v1/media/{quote(str(media_id), safe='')}"
                   f"?channel={self._channel_path(channel or self.channel)}",
            uncertainty="temporary", timeout=(self.connect_timeout, 120.0),
            raw_response=True)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise BridgeError("permanent", "bridge media download empty")
        return bytes(content), "application/octet-stream"

    def react(self, channel: str, message_id: str, emoji: str) -> dict:
        return self.request("POST", "/v1/messages/react", json_body={
            "channel": channel, "message_id": message_id, "emoji": emoji,
            "shadow": self.shadow})

    def mark_read(self, channel: str, message_ids: list[str]) -> dict:
        return self.request("POST", "/v1/messages/read", json_body={
            "channel": channel, "message_ids": list(message_ids)[:50],
            "shadow": self.shadow})

    # ---- probes (short-bounded; honor the configured read timeout) -------
    def _probe_timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, min(self.read_timeout, 5.0))

    def health(self) -> dict:
        return self.request("GET", "/v1/health", timeout=self._probe_timeout())

    def sessions(self) -> dict:
        return self.request("GET", "/v1/sessions", timeout=self._probe_timeout())

    def reconnect(self, channel: str) -> dict:
        return self.request("POST", "/v1/session/reconnect",
                            json_body={"channel": channel},
                            timeout=(2.0, 30.0))

    def message_status(self, channel: str, external_message_id: str) -> dict:
        """Reconciliation hook (owner spec §45) — provider status query."""
        return self.request(
            "GET", f"/v1/messages/{quote(str(external_message_id), safe='')}"
                   f"?channel={self._channel_path(channel)}",
            timeout=(2.0, 10.0))


def bridge_health_probe(config: dict) -> dict:
    """Cheap process+session probe for health checks (fail-soft to dict).

    Returns {"process": "UP"|"DOWN", "session": state, "detail": str} — it
    NEVER raises: health presentation distinguishes states (owner spec §33).
    """
    transport = BridgeTransport(config)
    try:
        transport.health()
    except BridgeError as exc:
        return {"process": "DOWN", "session": "UNKNOWN",
                "detail": str(exc)[:160]}
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        return {"process": "DOWN", "session": "UNKNOWN",
                "detail": str(exc)[:160]}
    try:
        sessions = transport.sessions() or {}
        state = ((sessions.get("sessions") or {}).get(transport.channel) or {})
        session = str(state.get("state") or "UNKNOWN")
        return {"process": "UP", "session": session,
                "detail": f"transport={state.get('transport', 'unknown')}"}
    except BridgeError as exc:
        return {"process": "UP", "session": "UNKNOWN", "detail": str(exc)[:160]}
