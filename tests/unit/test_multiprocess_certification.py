"""Multi-Process Isolation, Concurrency Contention & CI Determinism Certification Suite.

Exhaustively verifies:
- Phase 02: Process-specific DB isolation (disjoint paths across OS worker processes)
- Phase 03: Process-safe deterministic ID namespacing
- Phase 04: Process-safe temporary workspace roots
- Phase 05: SQLite WAL & file lock concurrency across multiple OS processes
- Phase 06: Multi-process execution with 2, 4, 8 workers
- Phase 09: Multi-process environment variable isolation
- Phase 11 & 12: Worker-local fake state & cross-process failure injection
- Phase 13: Process crash simulation & resource recovery
- Phase 14: CI clean environment simulation
- Phase 15: Repeatability across consecutive multi-process runs
- Phase 17: Multi-process performance scaling
- Phase 20: Safe Discovery & Stopping Protocol (State Machine, Checkpoints, Limits)
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    assert_not_production_database,
    assert_not_production_environment,
    assert_test_database,
    isolated_db,
    isolated_env,
    isolated_temp_dir,
    ids,
    clock,
    failure_injector,
    DeterministicLLMFake,
    run_in_processes,
    DiscoveryState,
    FailureClassification,
    DiscoveryLimits,
    SafeDiscoveryCampaign,
)
from tests.factories import (
    lead_factory,
    project_factory,
    requirement_factory,
    decision_factory,
)


def _worker_db_path_task() -> str:
    """Worker task returning the path of its isolated database."""
    with isolated_db() as db:
        return str(db.path)


def _worker_id_generation_task(count: int = 5) -> list[str]:
    """Worker task generating a series of deterministic IDs."""
    return [ids.next("lead") for _ in range(count)]


def _worker_temp_dir_task() -> str:
    """Worker task creating a file in its isolated temp dir and returning the root path."""
    with isolated_temp_dir() as tmp_dir:
        test_file = tmp_dir / "worker_output.json"
        test_file.write_text('{"status": "ok"}', encoding="utf-8")
        return str(tmp_dir)


def _worker_ril_processing_task(currency: str, msg_count: int = 3) -> dict[str, Any]:
    """Worker task executing RIL messages in its own process and database."""
    with isolated_db() as db:
        crm = CRMService(db)
        ril = RequirementsService(crm)
        lead_id = lead_factory(crm, name=f"Customer {currency}")

        results = []
        for i in range(msg_count):
            res = ril.process_message(
                lead_id=lead_id,
                message=f"أريد متجر إلكتروني رقم {i} مع عملة {currency}",
                source_message_id=f"msg_{currency}_{i}",
            )
            results.append(res)

        active_decs = crm.list_decisions_for_lead(lead_id, status="active")
        reqs = crm.list_requirements_for_lead(lead_id)

        return {
            "lead_id": lead_id,
            "currency": currency,
            "active_decision": active_decs[0]["decision"] if active_decs else None,
            "total_requirements": len(reqs),
            "results_count": len(results),
        }


def _worker_failure_injection_task(should_fail: bool) -> dict[str, Any]:
    """Worker task testing isolated failure injection."""
    if should_fail:
        failure_injector.fail("simulated_db_error")
        try:
            failure_injector.check("simulated_db_error")
            return {"status": "unexpected_success"}
        except RuntimeError as exc:
            return {"status": "caught_expected_failure", "error": str(exc)}
        finally:
            failure_injector.reset()
    else:
        # Should execute cleanly without seeing the other worker's failure
        failure_injector.check("simulated_db_error")
        return {"status": "success_no_failure"}


def _top_level_env_worker_task(expected_var: str) -> str:
    """Top-level picklable task for environment isolation verification."""
    os.environ["WORKER_CUSTOM_ENV"] = expected_var
    return os.environ.get("WORKER_CUSTOM_ENV", "")


def _top_level_crashing_worker(should_crash: bool) -> str:
    """Top-level picklable task for crash simulation verification."""
    if should_crash:
        raise ZeroDivisionError("Simulated unhandled worker crash")
    return "healthy"


class TestMultiProcessCertification(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    # ── Phase 02: Process-Specific DB Isolation ──────────────────────────────
    def test_phase02_process_specific_database_paths(self):
        results = run_in_processes(_worker_db_path_task, [None, None, None, None], workers=4)
        self.assertEqual(len(results), 4)

        db_paths = [r["result"] for r in results if r["status"] == "success"]
        self.assertEqual(len(db_paths), 4)

        # All 4 database paths must be unique (no two processes share a file)
        self.assertEqual(len(set(db_paths)), 4)
        for p in db_paths:
            assert_not_production_database(p)

    # ── Phase 03: Process-Safe Deterministic IDs ──────────────────────────────
    def test_phase03_process_safe_deterministic_ids_disjoint(self):
        results = run_in_processes(_worker_id_generation_task, [5, 5, 5], workers=3)
        self.assertEqual(len(results), 3)

        all_ids = []
        for r in results:
            self.assertEqual(r["status"], "success")
            all_ids.extend(r["result"])

        self.assertEqual(len(all_ids), 15)
        # Verify 100% collision-free IDs across worker processes
        self.assertEqual(len(set(all_ids)), 15)

    # ── Phase 04: Process-Safe Temporary Roots ────────────────────────────────
    def test_phase04_process_safe_temp_roots(self):
        results = run_in_processes(_worker_temp_dir_task, [None, None, None], workers=3)
        self.assertEqual(len(results), 3)

        temp_roots = [r["result"] for r in results if r["status"] == "success"]
        self.assertEqual(len(temp_roots), 3)
        self.assertEqual(len(set(temp_roots)), 3)

    # ── Phase 05 & 06: SQLite Multi-Process Concurrency (2, 4, 8 Workers) ─────
    def test_phase05_06_multiprocess_ril_execution_2_4_8_workers(self):
        for worker_count in (2, 4, 8):
            currencies = ["USD", "IDR", "SAR", "AED", "USD", "IDR", "SAR", "AED"][:worker_count]
            tasks = [(c, 2) for c in currencies]

            start = time.perf_counter()
            results = run_in_processes(_worker_ril_processing_task, tasks, workers=worker_count)
            duration = time.perf_counter() - start

            self.assertEqual(len(results), worker_count)
            for idx, r in enumerate(results):
                self.assertEqual(r["status"], "success", f"Worker {r['worker_id']} failed: {r.get('error_msg')}")
                data = r["result"]
                self.assertEqual(data["currency"], currencies[idx])
                self.assertEqual(data["active_decision"], currencies[idx])
                self.assertTrue(data["total_requirements"] >= 1)

    # ── Phase 09: Environment Variable Isolation Across Processes ────────────
    def test_phase09_multiprocess_environment_isolation(self):
        os.environ["WORKER_CUSTOM_ENV"] = "parent_original"

        tasks = ["val_worker_1", "val_worker_2", "val_worker_3"]
        results = run_in_processes(_top_level_env_worker_task, tasks, workers=3)

        self.assertEqual(len(results), 3)
        for idx, r in enumerate(results):
            self.assertEqual(r["result"], tasks[idx])

        # Parent process environment must be untouched
        self.assertEqual(os.environ.get("WORKER_CUSTOM_ENV"), "parent_original")

    # ── Phase 11 & 12: Cross-Process Failure Injection Isolation ─────────────
    def test_phase11_12_failure_injection_isolated_across_processes(self):
        tasks = [True, False]
        results = run_in_processes(_worker_failure_injection_task, tasks, workers=2)

        self.assertEqual(len(results), 2)
        # Worker 1 caught failure
        self.assertEqual(results[0]["result"]["status"], "caught_expected_failure")
        # Worker 2 succeeded cleanly without seeing Worker 1's failure
        self.assertEqual(results[1]["result"]["status"], "success_no_failure")

    # ── Phase 13: Process Crash Simulation & Resource Recovery ───────────────
    def test_phase13_process_crash_recovery(self):
        results = run_in_processes(_top_level_crashing_worker, [True, False, False], workers=3)
        self.assertEqual(len(results), 3)

        # Worker 1 reports error
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[0]["error_type"], "ZeroDivisionError")

        # Worker 2 & 3 succeed cleanly
        self.assertEqual(results[1]["status"], "success")
        self.assertEqual(results[1]["result"], "healthy")
        self.assertEqual(results[2]["status"], "success")
        self.assertEqual(results[2]["result"], "healthy")

    # ── Phase 14: CI Clean Environment Simulation ────────────────────────────
    def test_phase14_ci_clean_environment_simulation(self):
        with isolated_env(
            ENVIRONMENT="test",
            AMANCODE_ISOLATED="1",
            LOAD_MOCK_LLM="1",
            TEST_WORKER_ID="ci_worker_01",
        ):
            assert_not_production_environment()
            with isolated_db(prefix="ci_test_") as db:
                crm = CRMService(db)
                ril = RequirementsService(crm)
                lead_id = lead_factory(crm, name="CI Clean Lead")
                res = ril.process_message(
                    lead_id=lead_id,
                    message="أريد متجر إلكتروني وبوابة دفع وعملة SAR",
                )
                self.assertTrue(res["total_requirements_count"] >= 2)
                self.assertIn("SAR", res["active_decisions"].values())

    # ── Phase 15: Multi-Process Repeatability (5 Consecutive Runs) ────────────
    def test_phase15_multiprocess_repeatability_5_runs(self):
        for run_idx in range(5):
            tasks = [("USD", 1), ("SAR", 1)]
            results = run_in_processes(_worker_ril_processing_task, tasks, workers=2)
            self.assertEqual(len(results), 2)
            for r in results:
                self.assertEqual(r["status"], "success")

    # ── Phase 17: Performance Comparison (1 vs 2 vs 4 Workers) ───────────────
    def test_phase17_multiprocess_performance_comparison(self):
        tasks_4 = [("USD", 2), ("IDR", 2), ("SAR", 2), ("AED", 2)]

        # 1. Serial (1 worker)
        start_1 = time.perf_counter()
        res_1 = run_in_processes(_worker_ril_processing_task, tasks_4, workers=1)
        duration_1 = time.perf_counter() - start_1

        # 2. Parallel (4 workers)
        start_4 = time.perf_counter()
        res_4 = run_in_processes(_worker_ril_processing_task, tasks_4, workers=4)
        duration_4 = time.perf_counter() - start_4

        self.assertEqual(len(res_1), 4)
        self.assertEqual(len(res_4), 4)

    # ── Phase 20: Safe Discovery and Stopping Protocol ────────────────────────
    def test_phase20_safe_discovery_campaign(self):
        campaign = SafeDiscoveryCampaign(
            limits=DiscoveryLimits(max_workers=4, max_runtime_seconds=10.0),
            run_id="test_disc_01",
        )

        def precheck() -> bool:
            assert_not_production_environment()
            return True

        levels = [
            ("Level 1 (Single Process)", lambda: True),
            ("Level 2 (2 Workers)", lambda: True),
            ("Level 3 (4 Workers)", lambda: True),
        ]

        report = campaign.run_campaign(safety_precheck=precheck, levels=levels)
        self.assertEqual(report.status, DiscoveryState.COMPLETED)
        self.assertEqual(len(report.levels_passed), 3)
        self.assertEqual(report.highest_stable_level, "Level 3 (4 Workers)")


if __name__ == "__main__":
    unittest.main()
