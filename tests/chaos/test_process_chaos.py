"""Multi-Process Chaos, Worker Crash Recovery & Progressive Stopping Test Suite."""

import os
import unittest
from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    assert_not_production_environment,
    isolated_db,
    run_in_processes,
    ids,
    clock,
    failure_injector,
    DiscoveryState,
    DiscoveryLimits,
    SafeDiscoveryCampaign,
)
from tests.factories import lead_factory


def _chaos_worker_task(currency: str, should_crash: bool) -> dict[str, str]:
    """Top-level task for multi-process chaos testing."""
    if should_crash:
        raise SystemError("Simulated critical worker process crash")

    with isolated_db() as db:
        crm = CRMService(db)
        ril = RequirementsService(crm)
        lead_id = lead_factory(crm, name=f"Process Chaos {currency}")
        ril.process_message(
            lead_id=lead_id,
            message=f"أريد متجر مع عملة {currency}",
            source_message_id=f"msg_pchaos_{currency}",
        )
        decs = crm.list_decisions_for_lead(lead_id, status="active")
        return {"lead_id": lead_id, "decision": decs[0]["decision"]}


class TestProcessChaos(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    def test_multiprocess_worker_crash_and_sibling_survival(self):
        # 4 workers: Worker 1 crashes, Workers 2, 3, 4 succeed
        tasks = [("USD", True), ("SAR", False), ("AED", False), ("IDR", False)]
        results = run_in_processes(_chaos_worker_task, tasks, workers=4)

        self.assertEqual(len(results), 4)

        # Worker 1 reported error
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[0]["error_type"], "SystemError")

        # Workers 2, 3, 4 completed successfully
        self.assertEqual(results[1]["status"], "success")
        self.assertEqual(results[1]["result"]["decision"], "SAR")

        self.assertEqual(results[2]["status"], "success")
        self.assertEqual(results[2]["result"]["decision"], "AED")

        self.assertEqual(results[3]["status"], "success")
        self.assertEqual(results[3]["result"]["decision"], "IDR")

    def test_safe_discovery_campaign_under_compound_chaos(self):
        campaign = SafeDiscoveryCampaign(
            limits=DiscoveryLimits(max_workers=4, max_runtime_seconds=15.0),
            run_id="chaos_campaign_01",
        )

        def precheck() -> bool:
            assert_not_production_environment()
            return True

        def level1():
            # Level 1: Single process DB & RIL run
            with isolated_db() as db:
                crm = CRMService(db)
                ril = RequirementsService(crm)
                lead_id = lead_factory(crm, name="L1 Lead")
                ril.process_message(lead_id=lead_id, message="أريد متجر ويب وعملة USD")

        def level2():
            # Level 2: 2 concurrent processes
            tasks = [("USD", False), ("SAR", False)]
            res = run_in_processes(_chaos_worker_task, tasks, workers=2)
            if any(r["status"] != "success" for r in res):
                raise RuntimeError("Level 2 multi-process error")

        def level3():
            # Level 3: 4 concurrent processes
            tasks = [("USD", False), ("SAR", False), ("AED", False), ("IDR", False)]
            res = run_in_processes(_chaos_worker_task, tasks, workers=4)
            if any(r["status"] != "success" for r in res):
                raise RuntimeError("Level 3 multi-process error")

        levels = [
            ("Level 1 (Single Process Chaos)", level1),
            ("Level 2 (2 Worker Processes Chaos)", level2),
            ("Level 3 (4 Worker Processes Chaos)", level3),
        ]

        report = campaign.run_campaign(safety_precheck=precheck, levels=levels)
        self.assertEqual(report.status, DiscoveryState.COMPLETED)
        self.assertEqual(len(report.levels_passed), 3)
        self.assertEqual(report.highest_stable_level, "Level 3 (4 Worker Processes Chaos)")


if __name__ == "__main__":
    unittest.main()
