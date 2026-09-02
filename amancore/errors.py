"""Typed error hierarchy for AmanCode."""


class AmanCodeError(Exception):
    """Base error."""


class ConfigError(AmanCodeError):
    """Configuration loading/validation failure."""


class BusinessBrainError(AmanCodeError):
    """Business Brain load/validation/versioning failure."""


class ValidationError(BusinessBrainError):
    """Business Brain content validation failure."""


class NotFoundError(AmanCodeError):
    """Requested entity does not exist."""


class IntegrityError(AmanCodeError):
    """Data integrity violation (duplicate id, FK, immutable mutation)."""


class CRMError(AmanCodeError):
    """CRM data-service failure."""


class EventError(AmanCodeError):
    """Canonical event validation/dispatch failure."""


class PolicyError(AmanCodeError):
    """Policy engine failure."""


class RiskError(AmanCodeError):
    """Risk engine failure."""


class ApprovalError(AmanCodeError):
    """Approval service failure."""


class AuditError(AmanCodeError):
    """Audit service failure."""


class RoutingError(AmanCodeError):
    """Model router failure."""


class PermissionDenied(AmanCodeError):
    """Actor attempted an operation outside its permission boundary."""


class ProductionNotEnabledError(AmanCodeError):
    """External send attempted while production_enabled=false (safety rule)."""

