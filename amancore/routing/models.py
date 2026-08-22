"""Model routing domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Task classes (config keys in models.yaml `task_routing`)
STRATEGY = "strategy"
REASONING = "reasoning"
PRICING = "pricing"
CODING = "coding"
ROUTINE = "routine"
CLASSIFICATION = "classification"
EXTRACTION = "extraction"
SUMMARIZATION = "summarization"
MULTIMODAL = "multimodal"

TASK_CLASSES = {
    STRATEGY, REASONING, PRICING, CODING, ROUTINE,
    CLASSIFICATION, EXTRACTION, SUMMARIZATION, MULTIMODAL,
}


@dataclass
class ProviderResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    raw: Any = None


@dataclass
class RoutingResult:
    provider: str
    model: str
    text: str
    task_class: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    status: str = "ok"


@dataclass
class UsageRecord:
    request_id: str
    provider: str
    model: str
    task_class: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    latency_ms: int
    status: str
    created_at: str = ""
