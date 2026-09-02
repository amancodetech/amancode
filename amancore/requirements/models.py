"""Data models and enums for Requirements Intelligence Layer (RIL)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Certainty(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    SYSTEM_GENERATED = "system_generated"


class Priority(str, Enum):
    MUST_HAVE = "must_have"
    SHOULD_HAVE = "should_have"
    NICE_TO_HAVE = "nice_to_have"


class Status(str, Enum):
    CAPTURED = "captured"
    CLARIFIED = "clarified"
    APPROVED = "approved"
    ESTIMATED = "estimated"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    REJECTED = "rejected"


def _clean_confidence(conf: Any) -> float:
    try:
        val = float(conf)
        if val != val:  # NaN check
            return 1.0
        return max(0.0, min(1.0, val))
    except (TypeError, ValueError):
        return 1.0


def _clean_priority(p: Any) -> str:
    val = str(p or "").lower().strip()
    valid = {e.value for e in Priority}
    return val if val in valid else Priority.MUST_HAVE.value


def _clean_certainty(c: Any) -> str:
    val = str(c or "").lower().strip()
    valid = {e.value for e in Certainty}
    return val if val in valid else Certainty.EXPLICIT.value


def _clean_question_priority(qp: Any) -> int:
    try:
        val = int(round(float(qp)))
        return max(1, min(100, val))
    except (TypeError, ValueError):
        return 50


@dataclass
class Requirement:
    title: str
    description: str
    category: str  # core_module | integration | ui_ux | workflow | security | localization | infrastructure | constraint
    subcategory: str | None = None
    priority: str = Priority.MUST_HAVE.value
    certainty: str = Certainty.EXPLICIT.value
    confidence: float = 1.0
    status: str = Status.CAPTURED.value
    parent_requirement_id: str | None = None
    source_message_id: str | None = None
    source_conversation_id: str | None = None
    acceptance_criteria: str | None = None
    technical_spec: str | None = None
    is_customer_requested: bool = True
    is_system_inferred: bool = False
    requirement_id: str | None = None
    lead_id: str | None = None
    project_id: str | None = None

    def __post_init__(self):
        self.confidence = _clean_confidence(self.confidence)
        self.priority = _clean_priority(self.priority)
        self.certainty = _clean_certainty(self.certainty)
        if self.certainty == Certainty.INFERRED.value:
            self.is_system_inferred = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "lead_id": self.lead_id,
            "project_id": self.project_id,
            "parent_requirement_id": self.parent_requirement_id,
            "category": str(self.category or "core_module").strip()[:64],
            "subcategory": str(self.subcategory).strip()[:64] if self.subcategory else None,
            "title": str(self.title or "").strip()[:200],
            "description": str(self.description or "").strip()[:2000],
            "priority": _clean_priority(self.priority),
            "status": str(self.status or Status.CAPTURED.value).strip()[:32],
            "certainty": _clean_certainty(self.certainty),
            "confidence": _clean_confidence(self.confidence),
            "source_message_id": str(self.source_message_id).strip()[:128] if self.source_message_id else None,
            "source_conversation_id": str(self.source_conversation_id).strip()[:128] if self.source_conversation_id else None,
            "acceptance_criteria": str(self.acceptance_criteria).strip()[:2000] if self.acceptance_criteria else None,
            "technical_spec": str(self.technical_spec).strip()[:2000] if self.technical_spec else None,
            "is_customer_requested": 1 if self.is_customer_requested else 0,
            "is_system_inferred": 1 if (self.is_system_inferred or self.certainty == Certainty.INFERRED.value) else 0,
        }


@dataclass
class RequirementConflict:
    requirement_a_id: str
    requirement_b_id: str
    conflict_type: str
    explanation: str
    conflict_id: str | None = None
    lead_id: str | None = None
    project_id: str | None = None
    status: str = "open"
    resolution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "lead_id": self.lead_id,
            "project_id": self.project_id,
            "requirement_a_id": str(self.requirement_a_id).strip(),
            "requirement_b_id": str(self.requirement_b_id).strip(),
            "conflict_type": str(self.conflict_type or "general_contradiction").strip()[:64],
            "explanation": str(self.explanation or "").strip()[:2000],
            "status": str(self.status or "open").strip()[:32],
            "resolution": str(self.resolution).strip()[:2000] if self.resolution else None,
        }


@dataclass
class ProjectDecision:
    topic: str
    decision: str
    rationale: str | None = None
    source_message_id: str | None = None
    decided_by: str = "customer"
    status: str = "active"
    decision_id: str | None = None
    lead_id: str | None = None
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "lead_id": self.lead_id,
            "project_id": self.project_id,
            "topic": str(self.topic or "").strip()[:64],
            "decision": str(self.decision or "").strip()[:255],
            "rationale": str(self.rationale).strip()[:2000] if self.rationale else None,
            "source_message_id": str(self.source_message_id).strip()[:128] if self.source_message_id else None,
            "decided_by": str(self.decided_by or "customer").strip()[:64],
            "status": str(self.status or "active").strip()[:32],
        }


@dataclass
class OpenQuestion:
    question: str
    priority: int = 50
    category: str | None = None
    reason: str | None = None
    requirement_id: str | None = None
    status: str = "open"
    question_id: str | None = None
    lead_id: str | None = None
    project_id: str | None = None

    def __post_init__(self):
        self.priority = _clean_question_priority(self.priority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "lead_id": self.lead_id,
            "project_id": self.project_id,
            "requirement_id": self.requirement_id,
            "question": str(self.question or "").strip()[:500],
            "reason": str(self.reason).strip()[:500] if self.reason else None,
            "priority": _clean_question_priority(self.priority),
            "category": str(self.category).strip()[:64] if self.category else None,
            "status": str(self.status or "open").strip()[:32],
        }


@dataclass
class CoverageReport:
    tier: str
    coverage_score: float  # 0.0 - 100.0
    covered_domains: list[str] = field(default_factory=list)
    missing_domains: list[str] = field(default_factory=list)
    critical_gaps: list[str] = field(default_factory=list)
    is_ready_for_proposal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "coverage_score": self.coverage_score,
            "covered_domains": self.covered_domains,
            "missing_domains": self.missing_domains,
            "critical_gaps": self.critical_gaps,
            "is_ready_for_proposal": self.is_ready_for_proposal,
        }


@dataclass
class ScopeItem:
    title: str
    description: str | None = None
    deliverable: str | None = None
    complexity: str = "standard"
    is_included: bool = True
    sort_order: int = 0
    requirement_id: str | None = None
    item_id: str | None = None
    version_id: str | None = None


@dataclass
class ScopeVersion:
    version_number: int
    items: list[ScopeItem] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    total_estimated_hours: float = 0.0
    status: str = "draft"
    version_id: str | None = None
    scope_id: str | None = None
