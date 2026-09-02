"""Canonical Inbound & Outbound Contracts and Error Models for RIL Integration."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RILErrorCategory(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    UNKNOWN_IDENTITY = "UNKNOWN_IDENTITY"
    AMBIGUOUS_PROJECT = "AMBIGUOUS_PROJECT"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    RIL_FAILURE = "RIL_FAILURE"
    DATABASE_FAILURE = "DATABASE_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    TIMEOUT = "TIMEOUT"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"

    # Compatibility aliases
    INVALID_INPUT = "INVALID_REQUEST"
    UNAUTHORIZED = "AUTHORIZATION_FAILURE"
    FORBIDDEN = "AUTHORIZATION_FAILURE"
    INTERNAL_ERROR = "RIL_FAILURE"
    DATABASE_ERROR = "DATABASE_FAILURE"
    PROVIDER_ERROR = "PROVIDER_FAILURE"


@dataclass
class CanonicalInboundMessage:
    """Normalized internal message structure across all channels."""

    event_id: str = ""
    channel: str = "unknown"
    provider: str = "generic"
    provider_message_id: str = ""
    external_user_id: str = ""
    external_chat_id: str | None = None
    lead_id: str = ""
    conversation_id: str | None = None
    project_id: str | None = None
    message_text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    received_at: float = field(default_factory=time.time)
    raw_event_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Optional alias fields for constructor flexibility
    message_id: str | None = None
    sender_id: str | None = None
    content: str | None = None
    timestamp: str | None = None

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"evt_{uuid.uuid4().hex}"
        if self.message_id and not self.provider_message_id:
            self.provider_message_id = self.message_id
        if self.sender_id and not self.external_user_id:
            self.external_user_id = self.sender_id
        if self.content and not self.message_text:
            self.message_text = self.content

    @property
    def canonical_message_id(self) -> str:
        return self.provider_message_id or self.event_id

    @property
    def canonical_sender_id(self) -> str:
        return self.external_user_id

    @property
    def canonical_content(self) -> str:
        return self.message_text


@dataclass
class CanonicalRILResponse:
    """Channel-neutral RIL processing response."""

    lead_id: str
    project_id: str | None = None
    conversation_id: str | None = None
    requirements_summary: dict[str, Any] = field(default_factory=dict)
    new_requirements: list[dict[str, Any]] = field(default_factory=list)
    updated_requirements: list[dict[str, Any]] = field(default_factory=list)
    new_requirements_count: int = 0
    total_requirements_count: int = 0
    active_decisions: dict[str, Any] = field(default_factory=dict)
    conflicts_count: int = 0
    coverage_score: float = 0.0
    covered_domains: list[str] = field(default_factory=list)
    missing_domains: list[str] = field(default_factory=list)
    critical_gaps: list[str] = field(default_factory=list)
    is_ready_for_proposal: bool = False
    next_question: str | None = None
    scope_changes: dict[str, Any] | None = None
    scope_version_number: int | None = None
    response_metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    processing_duration_ms: float = 0.0
    status: str = "success"
    error: str | None = None
    error_category: RILErrorCategory | None = None


@dataclass(frozen=True)
class RILEvent:
    """Structured RIL domain event with correlation IDs."""

    event_name: str
    lead_id: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    project_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)
