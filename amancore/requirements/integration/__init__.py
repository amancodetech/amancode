"""Requirements Intelligence Layer (RIL) Integration Package."""

from .models import (
    CanonicalInboundMessage,
    CanonicalRILResponse,
    RILErrorCategory,
    RILEvent,
)
from .resolver import ChannelProjectResolver, ResolvedContext
from .service import RILIntegrationService
from .dashboard import DashboardRILAPI
from .adapters import (
    BaseChannelAdapter,
    WhatsAppAdapter,
    TelegramAdapter,
    WebhookAdapter,
)

__all__ = [
    "CanonicalInboundMessage",
    "CanonicalRILResponse",
    "RILErrorCategory",
    "RILEvent",
    "ChannelProjectResolver",
    "ResolvedContext",
    "RILIntegrationService",
    "DashboardRILAPI",
    "BaseChannelAdapter",
    "WhatsAppAdapter",
    "TelegramAdapter",
    "WebhookAdapter",
]
