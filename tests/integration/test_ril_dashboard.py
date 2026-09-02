"""Integration Tests for Dashboard RIL API Layer & Mutation Governance."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import DashboardRILAPI
from amancore.requirements.service import RequirementsService
from tests.fixtures import isolated_db, ids, clock
from tests.factories import (
    lead_factory,
    requirement_factory,
    decision_factory,
    conflict_factory,
    question_factory,
)


class TestRILDashboardIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_dashboard_reads_and_mutation_governance(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            api = DashboardRILAPI(crm, ril)

            lead_id = lead_factory(crm, name="Dashboard Lead")
            auth_user = {"user_id": "usr_admin_01", "role": "admin"}

            # 1. Create entities via factories / domain
            req_id = requirement_factory(crm, lead_id=lead_id, title="User Auth Portal")
            dec_id = decision_factory(crm, lead_id=lead_id, topic="currency", decision="SAR")
            conf_id = conflict_factory(crm, lead_id=lead_id, requirement_a_id=req_id, requirement_b_id=req_id)
            q_id = question_factory(crm, lead_id=lead_id, question="What payment gateway?")

            # 2. Test Read APIs & Aggregated Dashboard View Model
            view = api.get_project_dashboard_view(lead_id, auth_user)
            self.assertEqual(view["lead_id"], lead_id)
            self.assertEqual(len(view["requirements"]), 1)
            self.assertEqual(len(view["active_decisions"]), 1)
            self.assertEqual(len(view["conflicts"]), 1)
            self.assertEqual(len(view["open_questions"]), 1)

            # 3. Test Mutation APIs (governed domain calls)
            # Confirm requirement
            api.confirm_requirement(lead_id, req_id, auth_user)
            updated_req = crm.list_requirements_for_lead(lead_id)[0]
            self.assertEqual(updated_req["status"], "confirmed")

            # Update decision (SAR -> USD)
            new_dec_id = api.update_decision(
                lead_id=lead_id,
                topic="currency",
                new_value="USD",
                rationale="Client requested USD switch on dashboard",
                auth_user=auth_user,
            )
            self.assertIsNotNone(new_dec_id)

            active_decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(len(active_decs), 1)
            self.assertEqual(active_decs[0]["decision"], "USD")

            # Answer open question
            api.answer_open_question(lead_id, q_id, answer="Stripe Gateway", auth_user=auth_user)
            open_qs = crm.list_open_questions_for_lead(lead_id, status="open")
            self.assertEqual(len(open_qs), 0)

            # Resolve conflict
            api.resolve_conflict(
                lead_id=lead_id,
                conflict_id=conf_id,
                resolution="Resolved via dashboard review",
                auth_user=auth_user,
            )
            open_confs = crm.list_conflicts_for_lead(lead_id, status="open")
            self.assertEqual(len(open_confs), 0)

            # Generate Scope
            scope_res = api.generate_scope(lead_id=lead_id, tier="website", auth_user=auth_user)
            self.assertEqual(scope_res["status"], "generated")
            self.assertEqual(scope_res["version_number"], 1)

            scope_view = api.get_scope(lead_id, auth_user)
            self.assertIsNotNone(scope_view)
            self.assertIsNotNone(scope_view["latest_version"])


if __name__ == "__main__":
    unittest.main()
