"""Requirements Service — central orchestrator for the Requirements Intelligence Layer (RIL)."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from .conflicts import ConflictDetector
from .coverage import CoverageAnalyzer
from .decisions import DecisionTracker
from .extractor import RequirementsExtractor
from .models import CoverageReport, OpenQuestion, ScopeVersion
from .questions import QuestionEngine
from .scope_builder import ScopeBuilder

log = logging.getLogger("amancore.requirements")


class RequirementsService:
    """End-to-end service coordinating requirements extraction, conflicts, decisions, coverage, and SOW generation."""

    def __init__(self, crm, brain_store=None):
        self.crm = crm
        self.brain_store = brain_store
        self.extractor = RequirementsExtractor()
        self.conflict_detector = ConflictDetector()
        self.coverage_analyzer = CoverageAnalyzer()
        self.decision_tracker = DecisionTracker(crm)
        self.question_engine = QuestionEngine()
        self.scope_builder = ScopeBuilder(crm)

    def process_message(
        self,
        lead_id: str,
        message: str,
        conversation_id: str | None = None,
        source_message_id: str | None = None,
        language: str = "ar",
        tier: str = "website",
    ) -> dict[str, Any]:
        """Analyze inbound message, persist discovered requirements and decisions, evaluate coverage, and select the next best question."""
        if not lead_id or not message:
            return {
                "lead_id": lead_id,
                "new_requirements_count": 0,
                "total_requirements_count": 0,
                "active_decisions": {},
                "conflicts_count": 0,
                "coverage_score": 0.0,
                "covered_domains": [],
                "missing_domains": [],
                "critical_gaps": [],
                "is_ready_for_proposal": False,
                "next_question": None,
                "scope_version_number": None,
            }

        try:
            # 1. Extract requirements & decisions
            extraction = self.extractor.extract(
                message=message,
                lead_id=lead_id,
                source_message_id=source_message_id,
                source_conversation_id=conversation_id,
            )

            # 2. Persist requirements (with idempotency and deduplication)
            existing_reqs = self.crm.list_requirements_for_lead(lead_id)
            existing_subcats = {r.get("subcategory"): r for r in existing_reqs if r.get("subcategory")}
            existing_source_msgs = {r.get("source_message_id") for r in existing_reqs if r.get("source_message_id")}

            new_req_ids = []
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            for req in extraction["requirements"]:
                # Check for existing requirement with same subcategory or from same source_message_id
                if req.subcategory and req.subcategory in existing_subcats:
                    old = existing_subcats[req.subcategory]
                    self.crm.update_requirement(
                        old["requirement_id"],
                        last_seen_at=now_iso,
                        confidence=max(old.get("confidence", 0.8), req.confidence),
                    )
                    log.debug("requirement.updated lead=%s req_id=%s subcat=%s", lead_id, old["requirement_id"], req.subcategory)
                elif source_message_id and source_message_id in existing_source_msgs:
                    # Message replay / retry — skip duplicate insert
                    log.debug("requirement.deduplicated lead=%s source_msg=%s", lead_id, source_message_id)
                else:
                    req_dict = req.to_dict()
                    req_id = self.crm.create_requirement(**req_dict)
                    new_req_ids.append(req_id)
                    log.info("requirement.extracted lead=%s id=%s subcat=%s certainty=%s", lead_id, req_id, req.subcategory, req.certainty)

            # 3. Persist decisions (with deduplication & change tracking)
            for dec in extraction["decisions"]:
                self.decision_tracker.record_decision(
                    lead_id=lead_id,
                    topic=dec.topic,
                    decision_value=dec.decision,
                    rationale=dec.rationale,
                    source_message_id=source_message_id,
                )

            # 4. Fetch updated requirements and decisions
            all_reqs = self.crm.list_requirements_for_lead(lead_id)
            all_decs = self.crm.list_decisions_for_lead(lead_id, status="active")
            dec_map = {d["topic"]: d["decision"] for d in all_decs}

            # 5. Detect and persist conflicts
            detected_conflicts = self.conflict_detector.detect_conflicts(
                requirements=all_reqs, decisions=all_decs, lead_id=lead_id
            )
            existing_conflicts = self.crm.list_conflicts_for_lead(lead_id, status="open")
            for conf in detected_conflicts:
                if not any(
                    ec["requirement_a_id"] == conf.requirement_a_id and ec["requirement_b_id"] == conf.requirement_b_id
                    for ec in existing_conflicts
                ):
                    self.crm.create_conflict(**conf.to_dict())

            # 6. Analyze Coverage
            coverage = self.coverage_analyzer.analyze(
                tier=tier,
                requirements=all_reqs,
                decisions=all_decs,
            )

            # 7. Select Next Question (avoiding repetition of answered or open questions)
            all_questions = self.crm.list_open_questions_for_lead(lead_id, status=None)
            answered_categories = {q.get("category") for q in all_questions if q.get("status") == "answered" and q.get("category")}
            open_categories = {q.get("category"): q for q in all_questions if q.get("status") == "open" and q.get("category")}

            next_q = self.question_engine.select_best_question(
                coverage_report=coverage,
                decisions=dec_map,
                requirements=all_reqs,
                answered_categories=answered_categories,
                language=language,
            )

            if next_q:
                if next_q.category in open_categories:
                    # Existing open question on same category — update priority if higher
                    existing_q = open_categories[next_q.category]
                    if next_q.priority > existing_q.get("priority", 0):
                        self.crm.update_open_question(existing_q["question_id"], priority=next_q.priority)
                else:
                    self.crm.create_open_question(
                        lead_id=lead_id,
                        question=next_q.question,
                        priority=next_q.priority,
                        category=next_q.category,
                        reason=next_q.reason,
                    )
                    log.info("question.created lead=%s cat=%s priority=%d", lead_id, next_q.category, next_q.priority)

            # 8. Build or update Scope version (idempotent, only versions if changed)
            scope_version = None
            if coverage.coverage_score >= 60.0 or len(all_reqs) >= 3:
                try:
                    scope_version = self.scope_builder.build_or_update_scope(lead_id, tier=tier)
                except Exception as exc:
                    log.warning("Scope building warning: %s", exc)

            return {
                "lead_id": lead_id,
                "new_requirements_count": len(new_req_ids),
                "total_requirements_count": len(all_reqs),
                "active_decisions": dec_map,
                "conflicts_count": len(detected_conflicts),
                "coverage_score": coverage.coverage_score,
                "covered_domains": coverage.covered_domains,
                "missing_domains": coverage.missing_domains,
                "critical_gaps": coverage.critical_gaps,
                "is_ready_for_proposal": coverage.is_ready_for_proposal,
                "next_question": next_q.question if next_q else None,
                "scope_version_number": scope_version.version_number if scope_version else None,
            }

        except Exception as exc:
            log.error("ril.failure lead=%s err=%s", lead_id, exc, exc_info=True)
            return {
                "lead_id": lead_id,
                "error": str(exc),
                "new_requirements_count": 0,
                "total_requirements_count": 0,
                "active_decisions": {},
                "conflicts_count": 0,
                "coverage_score": 0.0,
                "covered_domains": [],
                "missing_domains": [],
                "critical_gaps": [],
                "is_ready_for_proposal": False,
                "next_question": None,
                "scope_version_number": None,
            }
