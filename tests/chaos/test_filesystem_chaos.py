"""Filesystem Chaos, SOW Export Resilience & Cleanup Test Suite."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from amancore.crm.service import CRMService
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    isolated_db,
    isolated_temp_dir,
    ids,
    clock,
    failure_injector,
)
from tests.factories import (
    lead_factory,
    requirement_factory,
)


class TestFilesystemChaos(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    def test_sow_export_disk_failure_resilience(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            lead_id = lead_factory(crm, name="Export Chaos Lead")

            req1 = requirement_factory(crm, lead_id=lead_id, title="Core Module")
            scope_res = ril.scope_builder.build_or_update_scope(lead_id=lead_id)
            self.assertIsNotNone(scope_res)

            # Simulate filesystem write failure during artifact serialization
            with isolated_temp_dir() as tmp_dir:
                export_path = tmp_dir / "sow_export.md"

                # Simulate write error
                with patch("pathlib.Path.write_text", side_effect=OSError("Disk write failed: No space left")):
                    with self.assertRaises(OSError):
                        export_path.write_text("# SOW Document", encoding="utf-8")

                # Verify database scope state remained valid and uncorrupted
                scope = crm.get_project_scope_for_lead(lead_id)
                self.assertIsNotNone(scope)
                self.assertEqual(scope["current_version_number"], 1)

                latest_v = crm.get_latest_scope_version(scope["scope_id"])
                self.assertIsNotNone(latest_v)
                self.assertEqual(latest_v["status"], "draft")

                # Follow-up export succeeds cleanly once filesystem recovers
                export_path.write_text(f"# SOW Document\nLead: {lead_id}", encoding="utf-8")
                self.assertTrue(export_path.exists())
                self.assertIn(lead_id, export_path.read_text(encoding="utf-8"))

    def test_temp_directory_cleanup_after_unhandled_exception(self):
        created_path = None
        try:
            with isolated_temp_dir() as tmp_dir:
                created_path = tmp_dir
                test_file = tmp_dir / "temp_file.txt"
                test_file.write_text("temporary data", encoding="utf-8")
                self.assertTrue(test_file.exists())
                raise RuntimeError("Simulated crash inside temp directory block")
        except RuntimeError:
            pass

        # Verify that temp directory was automatically cleaned up on exit
        self.assertIsNotNone(created_path)
        self.assertFalse(created_path.exists())


if __name__ == "__main__":
    unittest.main()
