"""Model Router — config-driven task -> model -> fallback, with usage tracking."""

from __future__ import annotations

import time
from typing import Any

from ..errors import RoutingError
from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database
from .models import ProviderResult, RoutingResult, TASK_CLASSES
from .providers import Provider

log = get_logger("router")


class UsageTracker:
    def __init__(self, db: Database | None = None):
        self.db = db
        self.records: list[dict] = []

    def record(
        self,
        provider: str,
        model: str,
        task_class: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost: float,
        latency_ms: int,
        status: str,
    ) -> dict:
        rec = {
            "request_id": new_id(),
            "provider": provider,
            "model": model,
            "task_class": task_class,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "latency_ms": latency_ms,
            "status": status,
            "created_at": utcnow(),
        }
        self.records.append(rec)
        if self.db is not None:
            self.db.execute(
                "INSERT INTO usage_records "
                "(request_id, provider, model, task_class, input_tokens, output_tokens, "
                " estimated_cost, latency_ms, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["request_id"], rec["provider"], rec["model"], rec["task_class"],
                    rec["input_tokens"], rec["output_tokens"], rec["estimated_cost"],
                    rec["latency_ms"], rec["status"], rec["created_at"],
                ),
            )
            self.db.commit()
        return rec


class ModelRouter:
    def __init__(
        self,
        models_config: dict,
        providers: dict[str, Provider],
        usage: UsageTracker | None = None,
    ):
        self.config = models_config
        self.providers = providers
        self.usage = usage or UsageTracker()
        self.defaults = self.config.get("defaults", {})
        self.price_table = self.config.get("pricing_per_million", {})

    def classify(self, task_class: str) -> dict:
        if task_class not in TASK_CLASSES:
            raise RoutingError(f"unknown task_class: {task_class}")
        routing = self.config.get("task_routing", {}).get(task_class)
        if not routing:
            raise RoutingError(f"no routing configured for task_class: {task_class}")
        return routing

    def _estimate_cost(self, provider_id: str, result: ProviderResult) -> float:
        prices = self.price_table.get(provider_id, {})
        inp = prices.get("input", 0.0)
        out = prices.get("output", 0.0)
        return (result.input_tokens / 1_000_000) * inp + (result.output_tokens / 1_000_000) * out

    def _order(self, task_class: str) -> list[str]:
        r = self.classify(task_class)
        order = [r.get("primary"), r.get("secondary"), r.get("fallback")]
        return [p for p in order if p]

    def route(self, task_class: str, messages: list[dict], **kwargs: Any) -> RoutingResult:
        attempts = 0
        last_error: Exception | None = None
        for provider_id in self._order(task_class):
            provider = self.providers.get(provider_id)
            if provider is None:
                continue
            attempts += 1
            start = time.monotonic()
            try:
                result = provider.complete(messages, **kwargs)
                latency = int((time.monotonic() - start) * 1000)
                cost = self._estimate_cost(provider_id, result)
                self.usage.record(
                    provider_id, result.model, task_class,
                    result.input_tokens, result.output_tokens, cost, latency, "ok",
                )
                return RoutingResult(
                    provider=provider_id, model=result.model, text=result.text,
                    task_class=task_class, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens, estimated_cost=cost,
                    latency_ms=latency, attempts=attempts, status="ok",
                )
            except Exception as exc:  # noqa: BLE001 — fallback chain
                last_error = exc
                latency = int((time.monotonic() - start) * 1000)
                self.usage.record(provider_id, provider.model, task_class, 0, 0, 0.0, latency, "error")
                log.warning("provider %s failed for %s: %s", provider_id, task_class, exc)
        raise RoutingError(f"all providers failed for {task_class}: {last_error}")
