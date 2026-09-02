"""Unit tests for Requirements Intelligence Layer (RIL) services and components."""

import unittest
from pathlib import Path
import tempfile

from amancore.storage.db import open_database
from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from amancore.requirements.extractor import RequirementsExtractor
from amancore.requirements.conflicts import ConflictDetector
from amancore.requirements.coverage import CoverageAnalyzer


class TestRequirementsIntelligenceLayer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_aman.db"
        schema_path = Path(__file__).resolve().parents[2] / "amancore" / "storage" / "schema.sql"
        self.db = open_database(db_path, schema_path)
        self.crm = CRMService(self.db)
        self.ril = RequirementsService(self.crm)
        self.lead_id = self.crm.create_lead(name="Omar Merchant", contact_whatsapp="628123456789")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_extractor_explicit_vs_inferred(self):
        extractor = RequirementsExtractor()
        
        # Explicit statement
        res_exp = extractor.extract(
            "أريد متجر إلكتروني لبيع العطور مع ربط بوابة الدفع Stripe وباللغتين عربي وإنجليزي",
            lead_id=self.lead_id,
            source_message_id="msg_001",
        )
        reqs_exp = res_exp["requirements"]
        self.assertTrue(len(reqs_exp) >= 2)
        ecommerce_req = next(r for r in reqs_exp if r.subcategory == "ecommerce")
        self.assertEqual(ecommerce_req.certainty, "explicit")
        self.assertTrue(ecommerce_req.confidence >= 0.95)
        self.assertEqual(ecommerce_req.source_message_id, "msg_001")

        # Inferred statement
        res_inf = extractor.extract(
            "أفكر في إمكانية إضافة حجوزات مستقبلاً",
            lead_id=self.lead_id,
            source_message_id="msg_002",
        )
        reqs_inf = res_inf["requirements"]
        booking_req = next(r for r in reqs_inf if r.subcategory == "booking")
        self.assertEqual(booking_req.certainty, "inferred")

        # Decisions extracted
        decs = res_exp["decisions"]
        self.assertTrue(any(d.topic == "languages" and "Arabic + English" in d.decision for d in decs))

    def test_conflict_detection(self):
        detector = ConflictDetector()
        reqs = [
            {"requirement_id": "r1", "subcategory": "no_auth", "title": "No Auth"},
            {"requirement_id": "r2", "subcategory": "auth_members", "title": "Member Accounts"},
        ]
        conflicts = detector.detect_conflicts(reqs, lead_id=self.lead_id)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].conflict_type, "mutual_exclusion")

    def test_coverage_analysis_and_readiness(self):
        analyzer = CoverageAnalyzer()
        
        # Partial requirements
        reqs_initial = [
            {"category": "core_module", "subcategory": "ecommerce"},
        ]
        rep_init = analyzer.analyze("website", requirements=reqs_initial)
        self.assertFalse(rep_init.is_ready_for_proposal)
        self.assertIn("Language & Market", rep_init.missing_domains)

        # Complete requirements
        reqs_full = [
            {"category": "core_module", "subcategory": "ecommerce"},
            {"category": "integration", "subcategory": "messaging"},
            {"category": "ui_ux", "subcategory": "dynamic_content"},
        ]
        decs_full = [
            {"topic": "languages", "decision": "Indonesian + English", "status": "active"},
            {"topic": "currency", "decision": "IDR", "status": "active"},
        ]
        rep_full = analyzer.analyze("website", requirements=reqs_full, decisions=decs_full)
        self.assertTrue(rep_full.coverage_score >= 80.0)
        self.assertTrue(rep_full.is_ready_for_proposal)

    def test_end_to_end_ril_service(self):
        # Step 1: Customer describes store
        res1 = self.ril.process_message(
            lead_id=self.lead_id,
            message="مرحبا، أحتاج متجر إلكتروني باللغة العربية والإنجليزية، ونريد ربط واتساب للإشعارات بالعملة بالروبية IDR",
            conversation_id="conv_1",
            source_message_id="msg_1",
            language="ar",
            tier="website",
        )
        self.assertTrue(res1["total_requirements_count"] >= 2)
        self.assertEqual(res1["active_decisions"].get("currency"), "IDR")
        self.assertIsNotNone(res1["next_question"])

        # Step 2: Customer adds payment requirement
        res2 = self.ril.process_message(
            lead_id=self.lead_id,
            message="نعم ونريد أيضاً تفعيل بوابة دفع إلكتروني بالبطاقات والدفع عند الاستلام",
            conversation_id="conv_1",
            source_message_id="msg_2",
            language="ar",
            tier="website",
        )
        self.assertTrue(res2["total_requirements_count"] >= 3)
        self.assertTrue(res2["coverage_score"] >= 60.0)
        self.assertIsNotNone(res2["scope_version_number"])

        # Verify database records
        db_reqs = self.crm.list_requirements_for_lead(self.lead_id)
        self.assertTrue(len(db_reqs) >= 3)
        
        db_scope = self.crm.get_project_scope_for_lead(self.lead_id)
        self.assertIsNotNone(db_scope)
        
        latest_v = self.crm.get_latest_scope_version(db_scope["scope_id"])
        self.assertIsNotNone(latest_v)
        items = self.crm.list_scope_items(latest_v["version_id"])
        self.assertTrue(len(items) >= 3)


if __name__ == "__main__":
    unittest.main()
