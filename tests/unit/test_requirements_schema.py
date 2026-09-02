"""Unit tests for Requirements Intelligence Layer (RIL) database tables and CRMService operations."""

import unittest
from pathlib import Path
import tempfile

from amancore.storage.db import open_database
from amancore.crm.service import CRMService


class TestRequirementsSchema(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_aman.db"
        schema_path = Path(__file__).resolve().parents[2] / "amancore" / "storage" / "schema.sql"
        self.db = open_database(db_path, schema_path)
        self.crm = CRMService(self.db)
        self.lead_id = self.crm.create_lead(name="Omar Client", contact_whatsapp="628123456789")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_requirement_crud_and_traceability(self):
        req_id = self.crm.create_requirement(
            lead_id=self.lead_id,
            category="integration",
            subcategory="payments",
            title="Online Payment Gateway",
            description="Integration with Midtrans/Stripe for online checkout",
            priority="must_have",
            certainty="explicit",
            confidence=0.98,
            source_message_id="msg_101",
            source_conversation_id="conv_202",
        )
        self.assertIsNotNone(req_id)
        
        req = self.crm.get_requirement(req_id)
        self.assertEqual(req["title"], "Online Payment Gateway")
        self.assertEqual(req["certainty"], "explicit")
        self.assertEqual(req["source_message_id"], "msg_101")
        self.assertEqual(req["confidence"], 0.98)

        # Update requirement status
        self.crm.update_requirement(req_id, status="clarified", technical_spec="Stripe Elements API")
        req_updated = self.crm.get_requirement(req_id)
        self.assertEqual(req_updated["status"], "clarified")
        self.assertEqual(req_updated["technical_spec"], "Stripe Elements API")

        # List by lead
        reqs = self.crm.list_requirements_for_lead(self.lead_id)
        self.assertEqual(len(reqs), 1)

    def test_conflicts_and_resolutions(self):
        req_a = self.crm.create_requirement(
            lead_id=self.lead_id, category="core_module", title="No Authentication", description="Public access only"
        )
        req_b = self.crm.create_requirement(
            lead_id=self.lead_id, category="core_module", title="Private User Accounts", description="Individual profile and dashboard"
        )

        conflict_id = self.crm.create_conflict(
            lead_id=self.lead_id,
            requirement_a_id=req_a,
            requirement_b_id=req_b,
            conflict_type="mutual_exclusion",
            explanation="Customer requested both no login and private user accounts",
        )

        conflicts = self.crm.list_conflicts_for_lead(self.lead_id)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["status"], "open")

        # Resolve
        self.crm.resolve_conflict(conflict_id, resolution="Guest checkout + optional registration")
        conflicts_open = self.crm.list_conflicts_for_lead(self.lead_id, status="open")
        self.assertEqual(len(conflicts_open), 0)

    def test_decisions_log(self):
        dec_id = self.crm.create_decision(
            lead_id=self.lead_id,
            topic="currency",
            decision="IDR",
            rationale="Primary target market is Indonesia",
            source_message_id="msg_105",
        )
        self.assertIsNotNone(dec_id)

        decisions = self.crm.list_decisions_for_lead(self.lead_id)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["topic"], "currency")
        self.assertEqual(decisions[0]["decision"], "IDR")

    def test_open_questions_prioritized(self):
        q1 = self.crm.create_open_question(
            lead_id=self.lead_id,
            question="What payment gateway do you prefer?",
            priority=80,
            category="integration",
        )
        q2 = self.crm.create_open_question(
            lead_id=self.lead_id,
            question="Do you have high-res product photos ready?",
            priority=40,
            category="assets",
        )

        next_q = self.crm.get_next_open_question(self.lead_id)
        self.assertIsNotNone(next_q)
        self.assertEqual(next_q["question_id"], q1)
        self.assertEqual(next_q["priority"], 80)

        # Mark q1 answered
        self.crm.update_open_question(q1, status="answered", answer_message_id="msg_110")
        next_q2 = self.crm.get_next_open_question(self.lead_id)
        self.assertEqual(next_q2["question_id"], q2)

    def test_versioned_scope_and_items(self):
        scope_id = self.crm.create_project_scope(
            lead_id=self.lead_id,
            tier="website",
            summary="Multilingual Business Website System",
        )
        v1_id = self.crm.create_scope_version(
            scope_id=scope_id,
            version_number=1,
            total_estimated_hours=40.0,
            assumptions='["Client provides text copy in Arabic"]',
            exclusions='["Mobile native application"]',
        )

        self.crm.add_scope_item(
            version_id=v1_id,
            title="Landing & Service Pages",
            description="Home, Services, About, Contact with WhatsApp integration",
            deliverable="Fully responsive frontend",
            sort_order=1,
        )

        items = self.crm.list_scope_items(v1_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Landing & Service Pages")


if __name__ == "__main__":
    unittest.main()
