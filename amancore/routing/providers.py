"""Model provider adapters (API-based only; no local/GPU inference).

Each adapter reads base_url/api_key from environment variables referenced
by the models config. Secrets never appear in code.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from ..errors import RoutingError
from .models import ProviderResult


class Provider:
    def __init__(self, provider_id: str, config: dict):
        self.provider_id = provider_id
        self.config = config
        self.model = config.get("model", provider_id)

    def _api_key(self) -> str:
        env_name = self.config.get("api_key_env")
        key = os.environ.get(env_name or "", "")
        if not key:
            raise RoutingError(f"provider {self.provider_id} not configured (missing {env_name})")
        return key

    def _base_url(self) -> str:
        env_name = self.config.get("base_url_env")
        url = os.environ.get(env_name or "", "")
        if not url:
            raise RoutingError(f"provider {self.provider_id} not configured (missing {env_name})")
        return url.rstrip("/")

    def complete(self, messages: list[dict], **kwargs: Any) -> ProviderResult:
        raise NotImplementedError


class OpenAICompatibleProvider(Provider):
    """OpenAI-compatible /chat/completions.

    Text messages use {"role": .., "content": "str"}.
    Vision messages use {"role": "user", "content": [..]} with
    {"type": "text", ..} + {"type": "image_url", "image_url": {"url": ..}}
    blocks — passed through verbatim, so deepseek-v4-flash-vision-exp
    (JPEG/PNG/GIF/WebP, user-messages-only) works without a vendor class.
    """

    def complete(self, messages: list[dict], **kwargs: Any) -> ProviderResult:
        url = f"{self._base_url()}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        max_tokens = kwargs.get("max_tokens", self.config.get("max_tokens"))
        payload = {"model": self.model, "messages": messages}
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        # config-injected extras (e.g. thinking level) — never override core fields
        for k, v in (self.config.get("extra_payload") or {}).items():
            payload.setdefault(k, v)
        resp = requests.post(url, json=payload, headers=headers, timeout=kwargs.get("timeout", 60))
        if resp.status_code != 200:
            raise RoutingError(f"{self.provider_id} HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        usage = data.get("usage", {})
        return ProviderResult(
            text=data["choices"][0]["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=self.model,
            raw=data,
        )


class AnthropicProvider(Provider):
    def complete(self, messages: list[dict], **kwargs: Any) -> ProviderResult:
        url = f"{self._base_url()}/v1/messages"
        headers = {
            "x-api-key": self._api_key(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        system = " ".join(m["content"] for m in messages if m.get("role") == "system")
        user_msgs = [m for m in messages if m.get("role") != "system"]
        payload = {"model": self.model, "max_tokens": kwargs.get("max_tokens", 1024), "messages": user_msgs}
        if system:
            payload["system"] = system
        resp = requests.post(url, json=payload, headers=headers, timeout=kwargs.get("timeout", 60))
        if resp.status_code != 200:
            raise RoutingError(f"{self.provider_id} HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        usage = data.get("usage", {})
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return ProviderResult(
            text=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            model=self.model,
            raw=data,
        )


class GeminiProvider(Provider):
    def complete(self, messages: list[dict], **kwargs: Any) -> ProviderResult:
        try:
            from google import genai  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RoutingError("google-genai SDK not installed") from exc

        client = genai.Client(api_key=self._api_key())
        prompt = "\n".join(m.get("content", "") for m in messages)
        resp = client.models.generate_content(model=self.model, contents=prompt)
        usage = getattr(resp, "usage_metadata", None)
        return ProviderResult(
            text=getattr(resp, "text", "") or "",
            input_tokens=getattr(usage, "prompt_token_count", 0) if usage else 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) if usage else 0,
            model=self.model,
            raw=resp,
        )


_PROVIDER_TYPES = {
    "openai_compatible": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def build_providers(models_config: dict) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    for pid, pconf in (models_config.get("providers") or {}).items():
        ptype = pconf.get("type")
        cls = _PROVIDER_TYPES.get(ptype)
        if cls is None:
            raise RoutingError(f"unknown provider type for {pid}: {ptype}")
        providers[pid] = cls(pid, pconf)
    return providers
