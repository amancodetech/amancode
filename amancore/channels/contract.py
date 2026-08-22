"""Channel adapter contract — channels are transport, never business logic."""

from __future__ import annotations


class ChannelAdapter:
    channel = "generic"

    def send(self, recipient: str, message_type: str, payload) -> dict:
        raise NotImplementedError

    def receive_webhook(self, body, headers=None) -> list:
        raise NotImplementedError

    def verify_webhook(self, **params) -> dict:
        raise NotImplementedError
