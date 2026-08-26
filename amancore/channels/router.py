"""ChannelRouter — the single registry the Core uses to reach adapters.

The Outbox/worker NEVER instantiates a provider adapter; it asks the router.
Adding a channel = registering an adapter here, nothing else.
"""

from __future__ import annotations

from .canonical import ChannelCapabilities, TEXT_ONLY
from .contract import ChannelAdapter


class ChannelRouter:
    def __init__(self, adapters: dict[str, ChannelAdapter]):
        self._adapters: dict[str, ChannelAdapter] = dict(adapters or {})

    def register(self, adapter: ChannelAdapter) -> None:
        channel = getattr(adapter, "channel", None)
        if not channel:
            raise ValueError("adapter must define a 'channel' attribute")
        self._adapters[channel] = adapter

    def channels(self) -> list[str]:
        return sorted(self._adapters)

    def adapter_for(self, channel: str) -> ChannelAdapter | None:
        return self._adapters.get(channel)

    def has(self, channel: str) -> bool:
        return channel in self._adapters

    def capabilities(self, channel: str) -> ChannelCapabilities:
        adapter = self._adapters.get(channel)
        if adapter is None:
            return TEXT_ONLY
        caps = getattr(adapter, "capabilities", None)
        return caps() if callable(caps) else TEXT_ONLY

    def __contains__(self, channel: str) -> bool:
        return self.has(channel)
