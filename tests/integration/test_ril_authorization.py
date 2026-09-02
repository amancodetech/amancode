"""Integration Tests for Project-Scoped Authorization Boundaries."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import DashboardRILAPI
from amancore.requirements.service import RequirementsService
from tests.fixtures import isolated_db, ids, clock
from tests.factories import (
    lead_factory,
    requirement_factory,
    decision_factory,
)


class TestRILAuthorizationIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_project_scoped_authorization_enforcement(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            api = DashboardRILAPI(crm, ril)

            lead_a = lead_factory(crm, name="Client Alpha")
            lead_b = lead_factory(crm, name="Client Beta")

            requirement_factory(crm, lead_id=lead_a, title="Alpha Portal")
            requirement_factory(crm, lead_id=lead_b, title="Beta Mobile App")

            # User 1 has access ONLY to Lead A
            user_1 = {"user_id": "usr_alpha_manager", "role": "client", "allowed_leads": [lead_a]}

            # User 2 has access ONLY to Lead B
            user_2 = {"user_id": "usr_beta_manager", "role": "client", "allowed_leads": [lead_b]}

            # 1. User 1 accessing Lead A -> SUCCESS
            reqs_a = api.get_requirements(lead_a, auth_user=user_1)
            self.assertEqual(len(reqs_a), 1)
            self.assertEqual(reqs_a[0]["title"], "Alpha Portal")

            # 2. User 1 accessing Lead B -> FORBIDDEN (PermissionError)
            with self.assertRaises(PermissionError) as ctx:
                api.get_requirements(lead_b, auth_user=user_1)
            self.assertIn("FORBIDDEN", str(ctx.exception))

            # 3. User 1 attempting mutation on Lead B -> FORBIDDEN
            with self.assertRaises(PermissionError):
                api.update_decision(
                    lead_id=lead_b,
                    topic="currency",
                    new_value="EUR",
                    rationale="Hacked change",
                    auth_user=user_1,
                )

            # 4. User 2 accessing Lead B -> SUCCESS
            reqs_b = api.get_requirements(lead_b, auth_user=user_2)
            self.assertEqual(len(reqs_b), 1)
            self.assertEqual(reqs_b[0]["title"], "Beta Mobile App")

            # 5. Missing auth -> UNAUTHORIZED
            with self.assertRaises(PermissionError) as ctx_none:
                api.get_requirements(lead_a, auth_user=None)
            self.assertIn("UNAUTHORIZED", str(ctx_none.exception))


if __name__ == "__main__":
    unittest.main()
