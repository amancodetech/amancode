"""Bridge Meta providers — Facebook Messenger + Instagram DM over the local
meta-bridge (facebook-chat-api / instagram-private-api live ONLY inside the
bridge; owner spec §18).

Conservative Phase-1 surface: TEXT (matching the Meta adapters' practical
customer traffic). Media widens with the bridge implementation without any
AmanCore-side contract change (capabilities are per-adapter).

Identity parity (owner spec §16): facebook/instagram external ids and
idempotency keys (`fb:{mid}` / `ig:{mid}`) are preserved exactly like
MetaAdapterBase / Graph providers.
"""

from __future__ import annotations

import re

from ..log import get_logger
from ..production.gate import block_unless_production_enabled
from ..services.events import CanonicalEvent
from .bridge_transport import BridgeError, BridgeTransport, bridge_health_probe
from .canonical import ChannelCapabilities
from .contract import ChannelAdapter

log = get_logger("channels.bridge_meta")

MAX_TEXT = {"facebook": 2000, "instagram": 1000}


class BridgeMetaProvider:
    """Messenger/DM transport over the local meta-bridge."""

    def __init__(self, config: dict, channel: str):
        self.config = config
        self.channel = channel
        self.transport = BridgeTransport(config)

    def send(self, recipient: str, message_type: str, payload) -> dict:
        block_unless_production_enabled(self.config)
        if message_type != "text":
            raise BridgeError("invalid_request",
                              f"{self.channel} bridge carries text only "
                              f"(got '{message_type}')")
        body = payload if isinstance(payload, str) \
            else (payload or {}).get("body", "")
        message = {"type": "text", "recipient": recipient,
                   "text": str(body or "")[:MAX_TEXT.get(self.channel, 2000)]}
        result = self.transport.send_message(self.channel, message)
        return {"provider_message_id": str(result.get("external_message_id") or ""),
                "status": str(result.get("status") or "sent"),
                "would_send": bool(result.get("would_send"))}

    def health(self) -> dict:
        return self.transport.health()


class BridgeMetaAdapter(ChannelAdapter):
    """Base bridge adapter for facebook/instagram (webhook intake replaced by
    /bridge/inbound pushes)."""

    channel = ""
    capabilities_shape = ChannelCapabilities(text=True, read_receipt=True)

    def __init__(self, config: dict, provider=None):
        self.config = dict(config or {})
        self.provider = provider or BridgeMetaProvider(self.config, self.channel)

    # ---- contract surface ----------------------------------------------
    def capabilities(self) -> ChannelCapabilities:
        return self.capabilities_shape

    def normalize_recipient(self, raw) -> str:
        """IDENTITY PARITY: same opaque PSID/IG-id normalization as
        MetaAdapterBase — no new identity space is introduced."""
        psid = str(raw or "").strip()
        return re.sub(r"[^A-Za-z0-9_\-]", "", psid)

    # ---- webhook surface (unused in bridge mode) ------------------------
    def verify_webhook(self, mode: str = "", token: str = "",
                       challenge: str = "") -> dict:
        return {"verified": False,
                "error": f"{self.channel} bridge ingests via /bridge/inbound, "
                         "no Meta handshake"}

    def verify_signature(self, body_bytes: bytes, signature_header: str | None) -> bool:
        return False  # fail-closed: never accept Meta-signed posts in bridge mode

    def receive_webhook(self, body, headers=None) -> list[CanonicalEvent]:
        return []

    # ---- send / errors / ops -------------------------------------------
    def send(self, recipient: str, message_type: str, payload) -> dict:
        return self.provider.send(recipient, message_type, payload)

    def classify_error(self, exc: Exception) -> tuple[str | None, int | None]:
        if isinstance(exc, BridgeError):
            return exc.category, exc.retry_after_seconds
        return None, None

    def health_probe(self) -> str:
        state = bridge_health_probe(self.config)
        if state["process"] != "UP":
            raise RuntimeError(f"bridge DOWN: {state['detail']}")
        shadow = " shadow=ON" if self.config.get("bridge", {}).get("shadow") else ""
        return (f"bridge UP transport={self.config.get('bridge', {}).get('transport', '?')}"
                f"{shadow} session={state['session']}")


class BridgeFacebookAdapter(BridgeMetaAdapter):
    channel = "facebook"
    capabilities_shape = ChannelCapabilities(text=True, read_receipt=True)


class BridgeInstagramAdapter(BridgeMetaAdapter):
    channel = "instagram"
    capabilities_shape = ChannelCapabilities(text=True, read_receipt=True)


def build_meta_bridge_adapter(channel: str, config: dict) -> BridgeMetaAdapter:
    if channel == "facebook":
        return BridgeFacebookAdapter(config)
    if channel == "instagram":
        return BridgeInstagramAdapter(config)
    raise KeyError(f"no bridge meta adapter for channel '{channel}'")
