"""Typed error hierarchy for AmanCore."""


class AmanCoreError(Exception):
    """Base error."""


class ConfigError(AmanCoreError):
    """Configuration loading/validation failure."""


class BusinessBrainError(AmanCoreError):
    """Business Brain load/validation/versioning failure."""


class ValidationError(BusinessBrainError):
    """Business Brain content validation failure."""


class NotFoundError(AmanCoreError):
    """Requested entity does not exist."""


class IntegrityError(AmanCoreError):
    """Data integrity violation (duplicate id, FK, immutable mutation)."""


class CRMError(AmanCoreError):
    """CRM data-service failure."""


class EventError(AmanCoreError):
    """Canonical event validation/dispatch failure."""


class PolicyError(AmanCoreError):
    """Policy engine failure."""


class RiskError(AmanCoreError):
    """Risk engine failure."""


class ApprovalError(AmanCoreError):
    """Approval service failure."""


class AuditError(AmanCoreError):
    """Audit service failure."""


class RoutingError(AmanCoreError):
    """Model router failure."""


class PermissionDenied(AmanCoreError):
    """Actor attempted an operation outside its permission boundary."""
