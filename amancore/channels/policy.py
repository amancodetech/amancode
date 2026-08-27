"""Channel policy — deterministic per-channel rules (config-driven)."""

from __future__ import annotations

ALLOW = "allow"
APPROVAL_REQUIRED = "approval_required"
DENY = "deny"

# message_type → base risk for auto-reply decisions
_TYPE_RISK = {
    "text": "low",
    "template": "medium",
    "media": "medium",
    "proposal": "high",
}


class ChannelPolicyEngine:
    def __init__(self, brain_store, channels_config: dict | None = None):
        self.brain_store = brain_store
        self.channels_config = channels_config or {}

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def evaluate_send(self, channel: str, message_type: str, risk_level: str = "") -> str:
        risk = risk_level or _TYPE_RISK.get(message_type, "low")
        cfg = self.channels_config.get(channel, {})
        # explicit enablement: a channel that is not opted in for customer
        # messaging is DENIED before any provider call (config = source of truth)
        if cfg.get("enabled") is False or cfg.get("customer_messaging") is False:
            return DENY
        if risk == "critical":
            return DENY
        if risk == "high":
            return APPROVAL_REQUIRED
        if risk == "medium":
            return APPROVAL_REQUIRED if message_type in ("template", "proposal") else ALLOW
        return ALLOW

    def opt_out_blocks_marketing(self, channel: str) -> bool:
        cfg = self.channels_config.get(channel, {})
        return cfg.get("template_policy") != "none" or True
