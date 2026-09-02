"""Integration Tests for Transport Failures, Error Classifications & Resilience."""

import unittest
from unittest.mock import patch

from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    CanonicalInboundMessage,
    ChannelProjectResolver,
    RILIntegrationService,
    RILErrorCategory,
    WhatsAppAdapter,
)
from tests.fixtures import isolated_db, ids, clock


class TestRILIntegrationFailures(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_invalid_input_and_error_classification(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril_service = RILIntegrationService(crm)

            # Missing lead_id and content
            msg = CanonicalInboundMessage(
                provider_message_id="msg_err_01",
                lead_id="",
                channel="whatsapp",
                external_user_id="user_123",
                message_text="",
            )

            res = ril_service.ingest_canonical_message(msg)
            self.assertEqual(res.status, "error")
            self.assertEqual(res.error_category, RILErrorCategory.INVALID_REQUEST)

    def test_domain_failure_graceful_handling_and_event_logging(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril_service = RILIntegrationService(crm)

            msg = CanonicalInboundMessage(
                provider_message_id="msg_err_02",
                lead_id="lead_test_01",
                channel="telegram",
                external_user_id="user_456",
                message_text="أريد متجر إلكتروني",
            )

            # Simulate unhandled exception inside RequirementsService
            with patch.object(ril_service.ril, "process_message", side_effect=RuntimeError("Simulated LLM Crash")):
                res = ril_service.ingest_canonical_message(msg)
                self.assertEqual(res.status, "error")
                self.assertEqual(res.error_category, RILErrorCategory.RIL_FAILURE)
                self.assertIn("Simulated LLM Crash", res.error)

                # Verify failure event logged
                self.assertTrue(any(e.get("event_name") == "ril.failed" for e in res.events))

    def test_whatsapp_adapter_malformed_payload_handling(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = WhatsAppAdapter(resolver, ril_service)

            # Completely malformed payload
            malformed = {"random_key": 12345}
            res = adapter.handle_inbound(malformed)
            self.assertEqual(res["status"], "error")
            self.assertIn("Invalid or unauthenticated", res["error"])

    def test_unknown_identity_without_auto_create(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)

            resolved = resolver.resolve_context(
                channel="whatsapp",
                sender_id="unknown_user_9999",
                auto_create_lead=False,
            )
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.status, "unresolved")
            self.assertIn("UNKNOWN_IDENTITY", resolved.error_message)

    def test_ambiguous_projects_resolution_do_not_guess(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)

            # Create lead and 2 project scopes under the same lead
            lead_id = crm.create_lead(name="Multi Project Client", contact_whatsapp="905009998888")

            # Insert Customer and Projects to satisfy Foreign Key constraints
            crm.db.execute(
                "INSERT INTO customers (customer_id, created_at, updated_at) VALUES ('cust_multi', datetime('now'), datetime('now'))"
            )
            crm.db.execute(
                "INSERT INTO projects (project_id, customer_id, service, status, created_at, updated_at) VALUES ('proj_alpha', 'cust_multi', 'website', 'active', datetime('now'), datetime('now'))"
            )
            crm.db.execute(
                "INSERT INTO projects (project_id, customer_id, service, status, created_at, updated_at) VALUES ('proj_beta', 'cust_multi', 'web_app', 'active', datetime('now'), datetime('now'))"
            )

            crm.db.execute(
                "INSERT INTO project_scopes (scope_id, lead_id, project_id, tier, current_version_number, created_at, updated_at) VALUES ('scope_01', ?, 'proj_alpha', 'website', 1, datetime('now'), datetime('now'))",
                (lead_id,),
            )
            crm.db.execute(
                "INSERT INTO project_scopes (scope_id, lead_id, project_id, tier, current_version_number, created_at, updated_at) VALUES ('scope_02', ?, 'proj_beta', 'web_app', 1, datetime('now'), datetime('now'))",
                (lead_id,),
            )
            crm.db.commit()

            # Resolution without project hint must flag ambiguous project instead of guessing
            res = resolver.resolve_context(
                channel="whatsapp",
                sender_id="905009998888",
            )
            self.assertIsNotNone(res)
            self.assertTrue(res.is_ambiguous)
            self.assertEqual(res.status, "ambiguous")
            self.assertIn("AMBIGUOUS_PROJECT", res.error_message)


if __name__ == "__main__":
    unittest.main()
