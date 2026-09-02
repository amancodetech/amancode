"""Database Chaos, Transaction Failure & Rollback Resilience Test Suite."""

import os
import sqlite3
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    assert_not_production_database,
    assert_test_database,
    isolated_db,
    ids,
    clock,
    failure_injector,
)
from tests.factories import (
    lead_factory,
    requirement_factory,
    decision_factory,
)


class TestDatabaseChaos(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    def test_database_integrity_check_and_wal_mode(self):
        with isolated_db() as db:
            assert_test_database(db)
            # 1. Integrity check
            row = db.execute("PRAGMA integrity_check").fetchone()
            self.assertEqual(row[0], "ok")

            # 2. Journal mode
            j_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(j_mode.lower(), "wal")

            # 3. Foreign keys
            fk = db.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(fk, 1)

    def test_foreign_key_orphan_rejection(self):
        with isolated_db() as db:
            # Attempting to insert a requirement with nonexistent lead_id must raise IntegrityError
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    """
                    INSERT INTO requirements (
                        requirement_id, lead_id, project_id, category, subcategory, title,
                        description, confidence, status, first_seen_at, last_seen_at, created_at, updated_at
                    ) VALUES (
                        'req-orphan-01', 'nonexistent-lead', NULL, 'core_module', 'ecommerce',
                        'Orphan Req', 'desc', 0.9, 'stated', '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z',
                        '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z'
                    )
                    """
                )

    def test_transaction_rollback_and_connection_quarantine_resilience(self):
        with isolated_db() as db:
            crm = CRMService(db)
            lead_id = lead_factory(crm, name="Rollback Test Lead")

            # Insert initial requirement
            req_id = requirement_factory(crm, lead_id=lead_id, title="Baseline Req")
            self.assertEqual(len(crm.list_requirements_for_lead(lead_id)), 1)

            # Simulate failure during a multi-step transaction
            try:
                with db.transaction():
                    db.execute(
                        """
                        INSERT INTO requirements (
                            requirement_id, lead_id, project_id, category, subcategory, title,
                            description, confidence, status, first_seen_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'req-failing-01', ?, NULL, 'core_module', 'ecommerce', 'Failing Req',
                            'desc', 0.9, 'stated', '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z',
                            '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z'
                        )
                        """,
                        (lead_id,),
                    )
                    # Simulated disk / validation crash
                    raise RuntimeError("Simulated transaction abort")
            except RuntimeError as exc:
                self.assertIn("Simulated transaction abort", str(exc))

            # Verify complete rollback: no phantom row created
            reqs_after = crm.list_requirements_for_lead(lead_id)
            self.assertEqual(len(reqs_after), 1)
            self.assertEqual(reqs_after[0]["requirement_id"], req_id)

            # Verify integrity check passes
            row = db.execute("PRAGMA integrity_check").fetchone()
            self.assertEqual(row[0], "ok")

            # Follow-up transaction succeeds cleanly
            req_id_3 = requirement_factory(crm, lead_id=lead_id, title="Follow-up Req")
            self.assertEqual(len(crm.list_requirements_for_lead(lead_id)), 2)

    def test_concurrent_writer_contention_and_busy_handling(self):
        with isolated_db() as db:
            crm = CRMService(db)
            lead_id = lead_factory(crm, name="Concurrency Lead")

            errors = []

            def worker_writer(idx: int):
                try:
                    # Each thread operates on its thread-local connection
                    thread_crm = CRMService(db)
                    for i in range(5):
                        requirement_factory(
                            thread_crm,
                            lead_id=lead_id,
                            title=f"Worker-{idx}-Req-{i}",
                        )
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker_writer, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10.0)

            self.assertEqual(len(errors), 0, f"Encountered unexpected contention errors: {errors}")
            total_reqs = len(crm.list_requirements_for_lead(lead_id))
            self.assertEqual(total_reqs, 20)

    def test_project_isolation_under_aborted_transaction(self):
        with isolated_db() as db:
            crm = CRMService(db)
            lead_a = lead_factory(crm, name="Lead A")
            lead_b = lead_factory(crm, name="Lead B")

            requirement_factory(crm, lead_id=lead_a, title="Req A1")
            requirement_factory(crm, lead_id=lead_b, title="Req B1")

            # Attempt a failing transaction for Lead A
            try:
                with db.transaction():
                    db.execute(
                        """
                        INSERT INTO requirements (
                            requirement_id, lead_id, project_id, category, subcategory, title,
                            description, confidence, status, first_seen_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'req-failing-a2', ?, NULL, 'core_module', 'ecommerce', 'Req A2',
                            'desc', 0.9, 'stated', '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z',
                            '2026-09-02T12:00:00Z', '2026-09-02T12:00:00Z'
                        )
                        """,
                        (lead_a,),
                    )
                    raise ValueError("Abort A2")
            except ValueError:
                pass

            # Lead B must remain completely intact and unaffected
            reqs_b = crm.list_requirements_for_lead(lead_b)
            self.assertEqual(len(reqs_b), 1)
            self.assertEqual(reqs_b[0]["title"], "Req B1")

            # Lead A must only have A1
            reqs_a = crm.list_requirements_for_lead(lead_a)
            self.assertEqual(len(reqs_a), 1)
            self.assertEqual(reqs_a[0]["title"], "Req A1")


if __name__ == "__main__":
    unittest.main()
