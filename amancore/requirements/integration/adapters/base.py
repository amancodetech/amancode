"""Base Channel Adapter Interface for RIL Integration."""

from __future__ import annotations

import abc
from typing import Any

from ..models import CanonicalInboundMessage, CanonicalRILResponse
from ..resolver import ChannelProjectResolver
from ..service import RILIntegrationService


class BaseChannelAdapter(abc.ABC):
    """Abstract adapter defining the channel ingestion and response formatting lifecycle."""

    def __init__(self, resolver: ChannelProjectResolver, ril_service: RILIntegrationService):
        self.resolver = resolver
        self.ril_service = ril_service

    @abc.abstractmethod
    def validate_payload(self, raw_payload: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        """Validate raw incoming transport payload and authentication/signature."""
        raise NotImplementedError

    @abc.abstractmethod
    def normalize_to_canonical(
        self,
        raw_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> CanonicalInboundMessage | None:
        """Normalize validated transport payload into CanonicalInboundMessage."""
        raise NotImplementedError

    @abc.abstractmethod
    def format_response(self, ril_response: CanonicalRILResponse) -> dict[str, Any]:
        """Format channel-neutral RIL result into channel-specific outbound payload."""
        raise NotImplementedError

    def handle_inbound(
        self,
        raw_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Unified ingestion flow: validate -> normalize -> RIL ingest -> format response."""
        if not self.validate_payload(raw_payload, headers):
            return {"status": "error", "error": "Invalid or unauthenticated payload"}

        canonical_msg = self.normalize_to_canonical(raw_payload, headers)
        if canonical_msg is None:
            return {"status": "error", "error": "Failed to normalize message"}

        ril_res = self.ril_service.ingest_canonical_message(canonical_msg)
        return self.format_response(ril_res)
