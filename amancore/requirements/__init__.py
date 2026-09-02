"""Requirements Intelligence Layer (RIL) for AmanCore.

Transforms customer conversations into structured, traceable, conflict-resolved,
coverage-measured, and versioned project scopes and requirements.
"""

from .models import (
    Requirement,
    RequirementConflict,
    ProjectDecision,
    OpenQuestion,
    CoverageReport,
    ScopeVersion,
    ScopeItem,
    Certainty,
    Priority,
    Status,
)
from .extractor import RequirementsExtractor
from .conflicts import ConflictDetector
from .coverage import CoverageAnalyzer
from .decisions import DecisionTracker
from .questions import QuestionEngine
from .scope_builder import ScopeBuilder
from .service import RequirementsService

__all__ = [
    "Requirement",
    "RequirementConflict",
    "ProjectDecision",
    "OpenQuestion",
    "CoverageReport",
    "ScopeVersion",
    "ScopeItem",
    "Certainty",
    "Priority",
    "Status",
    "RequirementsExtractor",
    "ConflictDetector",
    "CoverageAnalyzer",
    "DecisionTracker",
    "QuestionEngine",
    "ScopeBuilder",
    "RequirementsService",
]
