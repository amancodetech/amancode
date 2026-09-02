"""Test Infrastructure Self-Test Suite.

Verifies:
- Database isolation & safety guards against production paths
- Schema & FK enforcement
- Deterministic ID generator & clock
- Domain entity factories (Lead, Project, Conversation, Message, Req, Decision, Conflict, Question, Scope)
- Multi-tenant cross-project isolation assertions
- Deterministic LLM mock & adversarial response modes
- NetworkGuard outbound socket blocking
- Deterministic failure injection (fail & fail_once)
- Replay & idempotency helpers
- Multithreaded concurrency runner
- Environment & temporary filesystem isolation & cleanup
"""

import os
import socket
import unittest
from pathlib import Path

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    assert_not_production_database,
    assert_not_production_environment,
    assert_test_database,
    isolated_db,
    transactional_db,
    wipe_db,
    ids,
    clock,
    DeterministicLLMFake,
    FakeMessagingProvider,
    FakePaymentProvider,
    failure_injector,
    replay_message,
    assert_replay_idempotent,
    run_concurrently,
    isolated_env,
    isolated_temp_dir,
    NetworkGuard,
    isolated_projects,
    assert_project_isolated,
    assert_no_cross_project_requirements,
    assert_no_cross_project_decisions,
    assert_no_cross_project_questions,
    assert_no_cross_project_conflicts,
    assert_no_cross_project_scopes,
)
from tests.factories import (
    lead_factory,
    project_factory,
    conversation_factory,
    message_factory,
    requirement_factory,
    decision_factory,
    decision_history_factory,
    conflict_factory,
    question_factory,
    scope_factory,
    scope_version_factory,
    scope_item_factory,
    scope_snapshot,
)


class TestInfrastructureSelfTest(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    # ── Database & Safety Tests ──────────────────────────────────────────────
    def test_database_is_not_production_guard(self):
        with self.assertRaises(RuntimeError):
            assert_not_production_database("aman_core.db")

        with self.assertRaises(RuntimeError):
            assert_not_production_database("/var/data/production.db")

    def test_isolated_db_lifecycle_and_cleanup(self):
        created_path = None
        with isolated_db(prefix="self_test_db_") as db:
            created_path = db.path
            self.assertTrue(Path(created_path).exists())
            assert_test_database(db)

            # Insert sample data
            crm = CRMService(db)
            lead_id = lead_factory(crm, name="Test Lead")
            self.assertIsNotNone(lead_id)

        # Verify DB directory cleaned up
        self.assertFalse(Path(created_path).exists())

    def test_schema_initialization_and_fk_enforcement(self):
        with isolated_db() as db:
            crm = CRMService(db)
            # Orphaned requirement with non-existent lead must fail FK check
            with self.assertRaises(Exception):
                crm.create_requirement(
                    lead_id="non_existent_lead_99",
                    category="core_module",
                    title="Orphaned Module",
                    description="FK Violation",
                )

    # ── Identifiers & Clock ──────────────────────────────────────────────────
    def test_deterministic_ids(self):
        self.assertEqual(ids.next("lead"), "lead-test-0001")
        self.assertEqual(ids.next("lead"), "lead-test-0002")
        self.assertEqual(ids.next("project"), "project-test-0001")

        ids.reset()
        self.assertEqual(ids.next("lead"), "lead-test-0001")

        scoped = ids.scoped("custom")
        self.assertEqual(scoped.next("msg"), "msg-custom-0001")

    def test_deterministic_clock(self):
        clock.freeze("2026-09-02T12:00:00+00:00")
        self.assertEqual(clock.now_iso(), "2026-09-02T12:00:00+00:00")

        clock.advance(60.0)
        self.assertEqual(clock.now_iso(), "2026-09-02T12:01:00+00:00")

    # ── Factories & Compositions ─────────────────────────────────────────────
    def test_entity_factories_composition(self):
        with isolated_db() as db:
            crm = CRMService(db)
            lead_id = lead_factory(crm, name="Enterprise Alpha")
            proj_id = project_factory(crm, service="Web App")
            conv_id = conversation_factory(crm, lead_id=lead_id)
            msg = message_factory(crm, lead_id=lead_id, body="Requirement message")
            req_id = requirement_factory(crm, lead_id=lead_id, project_id=proj_id)
            dec_id = decision_factory(crm, lead_id=lead_id, topic="currency", decision="SAR")
            q_id = question_factory(crm, lead_id=lead_id, question="Payment gateway?")
            scope_id = scope_factory(crm, lead_id=lead_id)
            ver_id = scope_version_factory(crm, scope_id=scope_id, version_number=1)
            item_id = scope_item_factory(crm, version_id=ver_id, requirement_id=req_id)

            snapshot = scope_snapshot(crm, ver_id)
            self.assertEqual(snapshot["version"]["version_number"], 1)
            self.assertEqual(len(snapshot["items"]), 1)
            self.assertEqual(snapshot["items"][0]["item_id"], item_id)

    def test_decision_history_factory(self):
        with isolated_db() as db:
            crm = CRMService(db)
            lead_id = lead_factory(crm)
            history_ids = decision_history_factory(
                crm,
                lead_id,
                [
                    ("currency", "USD"),
                    ("currency", "IDR"),
                    ("currency", "SAR"),
                ],
            )
            self.assertEqual(len(history_ids), 3)
            active_decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(len(active_decs), 1)
            self.assertEqual(active_decs[0]["decision"], "SAR")

    # ── Project / Tenant Isolation ───────────────────────────────────────────
    def test_project_tenant_isolation_assertions(self):
        with isolated_db() as db:
            crm = CRMService(db)
            projects = isolated_projects(crm)
            lead_a = projects["project_a"]["lead_id"]
            lead_b = projects["project_b"]["lead_id"]

            assert_project_isolated(crm, lead_a, lead_b)

    # ── Deterministic LLM Mock ───────────────────────────────────────────────
    def test_llm_mock_modes_and_adversarial_responses(self):
        llm = DeterministicLLMFake()

        # Valid mode
        llm.set_mode("valid")
        res = llm.route("extraction")
        self.assertIn("requirements", res.text)

        # Markdown mode
        llm.set_mode("markdown_codeblock")
        res_md = llm.route("extraction")
        self.assertTrue(res_md.text.startswith("```json"))

        # Provider failure mode
        llm.set_mode("provider_failure")
        with self.assertRaises(RuntimeError):
            llm.route("extraction")

    # ── Network Guard ────────────────────────────────────────────────────────
    def test_network_guard_blocks_outbound_connections(self):
        with NetworkGuard(allowed_hosts={"127.0.0.1"}):
            # Outbound call to 8.8.8.8 must be blocked
            s = socket.socket()
            try:
                with self.assertRaises(RuntimeError):
                    s.connect(("8.8.8.8", 53))
            finally:
                s.close()

    # ── Failure Injection ────────────────────────────────────────────────────
    def test_failure_injection_fail_and_fail_once(self):
        failure_injector.fail_once("db_write")
        with self.assertRaises(RuntimeError):
            failure_injector.check("db_write")

        # Second call should pass (single shot)
        failure_injector.check("db_write")

        # Persistent fail
        failure_injector.fail("llm_api")
        with self.assertRaises(RuntimeError):
            failure_injector.check("llm_api")
        with self.assertRaises(RuntimeError):
            failure_injector.check("llm_api")

        failure_injector.reset()
        failure_injector.check("llm_api")

    # ── Replay & Concurrency ─────────────────────────────────────────────────
    def test_replay_fixture(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            lead_id = lead_factory(crm)

            results = replay_message(
                ril=ril,
                lead_id=lead_id,
                message="أريد متجر إلكتروني ودفع إلكتروني",
                times=3,
            )
            self.assertEqual(len(results), 3)
            assert_replay_idempotent(results)

    def test_concurrency_runner(self):
        def worker_fn(val: int) -> int:
            return val * 2

        results = run_concurrently(worker_fn, [1, 2, 3, 4], workers=2)
        self.assertEqual(results, [2, 4, 6, 8])

    # ── Environment & Filesystem Isolation ───────────────────────────────────
    def test_environment_isolation(self):
        os.environ["TEST_ENV_VAR_ORIG"] = "original"
        with isolated_env(TEST_ENV_VAR_ORIG="mutated", NEW_TEMP_KEY="temporary"):
            self.assertEqual(os.environ["TEST_ENV_VAR_ORIG"], "mutated")
            self.assertEqual(os.environ["NEW_TEMP_KEY"], "temporary")

        # Must be restored
        self.assertEqual(os.environ["TEST_ENV_VAR_ORIG"], "original")
        self.assertNotIn("NEW_TEMP_KEY", os.environ)

    def test_temporary_filesystem_isolation(self):
        target_file = None
        with isolated_temp_dir() as tmp:
            self.assertTrue(tmp.exists())
            target_file = tmp / "test_file.txt"
            target_file.write_text("sample data", encoding="utf-8")
            self.assertTrue(target_file.exists())

        self.assertFalse(target_file.exists())


if __name__ == "__main__":
    unittest.main()
