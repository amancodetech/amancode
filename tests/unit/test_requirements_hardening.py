"""Deep Production Hardening & Audit Verification Tests for Requirements Intelligence Layer (RIL)."""

import unittest
from pathlib import Path
import tempfile

from amancore.storage.db import open_database
from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from amancore.requirements.models import (
    Requirement,
    ProjectDecision,
    OpenQuestion,
    CoverageReport,
    Certainty,
    Priority,
    Status,
    _clean_confidence,
    _clean_priority,
    _clean_certainty,
    _clean_question_priority,
)
from amancore.requirements.extractor import RequirementsExtractor
from amancore.requirements.conflicts import ConflictDetector
from amancore.requirements.coverage import CoverageAnalyzer
from amancore.requirements.decisions import DecisionTracker
from amancore.requirements.questions import QuestionEngine
from amancore.requirements.scope_builder import ScopeBuilder


class TestRequirementsHardening(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_aman.db"
        schema_path = Path(__file__).resolve().parents[2] / "amancore" / "storage" / "schema.sql"
        self.db = open_database(db_path, schema_path)
        self.crm = CRMService(self.db)
        self.ril = RequirementsService(self.crm)
        self.lead_a = self.crm.create_lead(name="Lead A Corp", contact_whatsapp="62811111111")
        self.lead_b = self.crm.create_lead(name="Lead B Ltd", contact_whatsapp="62822222222")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    # ── 1. Confidence & Enum Sanitization ──────────────────────────────────
    def test_model_field_sanitization_and_clamping(self):
        self.assertEqual(_clean_confidence(1.5), 1.0)
        self.assertEqual(_clean_confidence(-0.5), 0.0)
        self.assertEqual(_clean_confidence("invalid"), 1.0)
        self.assertEqual(_clean_confidence(float("nan")), 1.0)

        self.assertEqual(_clean_priority("CRITICAL"), Priority.MUST_HAVE.value)
        self.assertEqual(_clean_priority("should_have"), Priority.SHOULD_HAVE.value)

        self.assertEqual(_clean_certainty("guaranteed"), Certainty.EXPLICIT.value)
        self.assertEqual(_clean_certainty("inferred"), Certainty.INFERRED.value)

        self.assertEqual(_clean_question_priority(150), 100)
        self.assertEqual(_clean_question_priority(-10), 1)
        self.assertEqual(_clean_question_priority("75.4"), 75)

        req = Requirement(
            title="Custom Gateway",
            description="Testing boundaries",
            category="integration",
            confidence=2.5,
            priority="INVALID_PRIORITY",
            certainty="UNKNOWN_CERTAINTY",
        )
        d = req.to_dict()
        self.assertEqual(d["confidence"], 1.0)
        self.assertEqual(d["priority"], "must_have")
        self.assertEqual(d["certainty"], "explicit")

    # ── 2. Message-Level Idempotency & Deduplication ──────────────────────
    def test_message_idempotency_and_deduplication(self):
        msg = "أريد متجر إلكتروني لبيع الملابس مع بوابة دفع بالبطاقات"
        
        # Turn 1
        res1 = self.ril.process_message(
            lead_id=self.lead_a,
            message=msg,
            source_message_id="msg_retry_100",
            conversation_id="conv_100",
        )
        initial_count = res1["total_requirements_count"]
        self.assertTrue(initial_count >= 2)

        # Turn 2: Exact same message replayed (webhook retry)
        res2 = self.ril.process_message(
            lead_id=self.lead_a,
            message=msg,
            source_message_id="msg_retry_100",
            conversation_id="conv_100",
        )
        self.assertEqual(res2["total_requirements_count"], initial_count)
        self.assertEqual(res2["new_requirements_count"], 0)

        # Database rows must not have duplicated
        reqs = self.crm.list_requirements_for_lead(self.lead_a)
        self.assertEqual(len(reqs), initial_count)

    # ── 3. Decision Immutability & History Preservation ────────────────────
    def test_decision_evolution_and_history(self):
        tracker = DecisionTracker(self.crm)

        # Decision 1: Currency = USD
        id1 = tracker.record_decision(
            lead_id=self.lead_a,
            topic="currency",
            decision_value="USD",
            rationale="Initial discussion",
        )
        self.assertEqual(tracker.get_decision(self.lead_a, "currency"), "USD")

        # Duplicate call with same value (idempotent no-op)
        id1_dup = tracker.record_decision(
            lead_id=self.lead_a,
            topic="currency",
            decision_value="USD",
        )
        self.assertEqual(id1, id1_dup)

        # Decision 2: Currency updated to IDR (supersedes USD)
        id2 = tracker.record_decision(
            lead_id=self.lead_a,
            topic="currency",
            decision_value="IDR",
            rationale="Changed to local market",
        )
        self.assertNotEqual(id1, id2)
        self.assertEqual(tracker.get_decision(self.lead_a, "currency"), "IDR")

        # Verify historical audit log
        history = tracker.get_decision_history(self.lead_a, "currency")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["decision"], "USD")
        self.assertEqual(history[0]["status"], "superseded")
        self.assertEqual(history[1]["decision"], "IDR")
        self.assertEqual(history[1]["status"], "active")

    # ── 4. Scope Builder Immutability & Deduplication ──────────────────────
    def test_scope_version_immutability(self):
        builder = ScopeBuilder(self.crm)

        # Add initial requirement
        self.crm.create_requirement(
            lead_id=self.lead_a,
            category="core_module",
            subcategory="ecommerce",
            title="E-Commerce Catalog",
            description="Catalog module",
        )

        # Build Scope v1
        v1 = builder.build_or_update_scope(self.lead_a, tier="website")
        self.assertIsNotNone(v1)
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(len(v1.items), 1)

        # Repeated build without changing requirements (must NOT increment version)
        v1_repeat = builder.build_or_update_scope(self.lead_a, tier="website")
        self.assertEqual(v1_repeat.version_number, 1)

        # Add new requirement
        self.crm.create_requirement(
            lead_id=self.lead_a,
            category="integration",
            subcategory="payments",
            title="Payment Gateway",
            description="Stripe checkout",
        )

        # Build Scope v2
        v2 = builder.build_or_update_scope(self.lead_a, tier="website")
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(len(v2.items), 2)

        # Verify v1 items remain untouched in DB
        scope = self.crm.get_project_scope_for_lead(self.lead_a)
        v1_db_items = self.crm.list_scope_items(v1.version_id)
        self.assertEqual(len(v1_db_items), 1)

        v2_db_items = self.crm.list_scope_items(v2.version_id)
        self.assertEqual(len(v2_db_items), 2)

    # ── 5. Question Prioritization & Non-Repetition ───────────────────────
    def test_question_prioritization_and_non_repetition(self):
        engine = QuestionEngine()
        cov = CoverageReport(tier="website", coverage_score=30.0)

        # No requirements known yet -> core structure question
        q1 = engine.select_best_question(
            coverage_report=cov,
            decisions={},
            requirements=[],
            language="ar",
        )
        self.assertIsNotNone(q1)
        self.assertEqual(q1.category, "core_structure")
        self.assertTrue(q1.priority >= 90)

        # Once core structure answered, next question is selected
        q2 = engine.select_best_question(
            coverage_report=cov,
            decisions={},
            requirements=[{"subcategory": "ecommerce"}],
            answered_categories={"core_structure"},
            language="ar",
        )
        self.assertIsNotNone(q2)
        self.assertNotEqual(q2.category, "core_structure")

        # In service turn, verify question is not duplicated in DB
        self.ril.process_message(self.lead_a, "مرحبا أود بدء مشروع جديد")
        self.ril.process_message(self.lead_a, "أخبرني بالتفاصيل")

        questions = self.crm.list_open_questions_for_lead(self.lead_a, status="open")
        categories = [q["category"] for q in questions if q.get("category")]
        self.assertEqual(len(categories), len(set(categories)))  # no duplicate open categories

    # ── 6. Coverage Analysis Across Service Ladder ────────────────────────
    def test_coverage_tiers(self):
        analyzer = CoverageAnalyzer()
        
        # Website tier
        rep_web = analyzer.analyze("website", requirements=[{"category": "core_module", "subcategory": "ecommerce"}])
        self.assertTrue(0.0 <= rep_web.coverage_score <= 100.0)
        self.assertEqual(rep_web.tier, "website")

        # Custom Web App tier
        rep_app = analyzer.analyze("web_app", requirements=[{"category": "core_module", "subcategory": "core_workflow"}])
        self.assertEqual(rep_app.tier, "web_app")

        # Mini-ERP tier
        rep_erp = analyzer.analyze("mini_erp", requirements=[{"category": "core_module", "subcategory": "invoicing"}])
        self.assertEqual(rep_erp.tier, "mini_erp")

        # Mobile tier
        rep_mob = analyzer.analyze("mobile", requirements=[{"category": "core_module", "subcategory": "mobile_app"}])
        self.assertEqual(rep_mob.tier, "mobile")

        # Unknown fallback tier
        rep_fallback = analyzer.analyze("unknown_tier_xyz")
        self.assertEqual(rep_fallback.tier, "website")

    # ── 7. LLM Malformed JSON Defense ─────────────────────────────────────
    def test_llm_json_defense(self):
        extractor = RequirementsExtractor()

        # String with broken JSON
        res_broken = extractor.parse_llm_json("NOT_JSON_AT_ALL {broken: true}")
        self.assertEqual(len(res_broken["requirements"]), 0)

        # None / invalid object
        res_none = extractor.parse_llm_json(None)
        self.assertEqual(len(res_none["requirements"]), 0)

        # Valid JSON with out-of-bound types and missing fields
        raw_json = {
            "requirements": [
                {"name": "Valid Custom Flow", "category": "workflow", "confidence": 1.8},
                {"title": "", "category": "invalid_empty_title"},
                "just a string item",
            ],
            "decisions": [
                {"topic": "currency", "decision": "IDR"},
                "malformed item",
            ]
        }
        res_sanitized = extractor.parse_llm_json(raw_json, lead_id=self.lead_a)
        self.assertEqual(len(res_sanitized["requirements"]), 1)
        self.assertEqual(res_sanitized["requirements"][0].confidence, 1.0)
        self.assertEqual(len(res_sanitized["decisions"]), 1)
        self.assertEqual(res_sanitized["decisions"][0].decision, "IDR")

    # ── 8. Cross-Lead / Cross-Project Isolation ───────────────────────────
    def test_cross_lead_isolation(self):
        # Lead A requirements
        self.ril.process_message(
            lead_id=self.lead_a,
            message="أريد متجر إلكتروني باللغة العربية مع عملة SAR",
        )

        # Lead B requirements
        self.ril.process_message(
            lead_id=self.lead_b,
            message="نحتاج تطبيق جوال باللغة الإندونيسية وعملة IDR",
        )

        # Verify Lead A data
        reqs_a = self.crm.list_requirements_for_lead(self.lead_a)
        decs_a = self.crm.list_decisions_for_lead(self.lead_a)
        subcats_a = {r["subcategory"] for r in reqs_a}
        self.assertIn("ecommerce", subcats_a)
        self.assertNotIn("mobile_app", subcats_a)
        self.assertTrue(any(d["decision"] == "SAR" for d in decs_a))
        self.assertFalse(any(d["decision"] == "IDR" for d in decs_a))

        # Verify Lead B data
        reqs_b = self.crm.list_requirements_for_lead(self.lead_b)
        decs_b = self.crm.list_decisions_for_lead(self.lead_b)
        subcats_b = {r["subcategory"] for r in reqs_b}
        self.assertIn("mobile_app", subcats_b)
        self.assertNotIn("ecommerce", subcats_b)
        self.assertTrue(any(d["decision"] == "IDR" for d in decs_b))
        self.assertFalse(any(d["decision"] == "SAR" for d in decs_b))


if __name__ == "__main__":
    unittest.main()
