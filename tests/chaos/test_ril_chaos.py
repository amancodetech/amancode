"""RIL Resilience, Adversarial LLM Modes & Replay Chaos Test Suite."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.extractor import RequirementsExtractor
from amancore.requirements.service import RequirementsService
from tests.fixtures import (
    isolated_db,
    ids,
    clock,
    failure_injector,
    DeterministicLLMFake,
    replay_message,
    assert_replay_idempotent,
)
from tests.factories import (
    lead_factory,
    message_factory,
)


class TestRILChaos(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()
        failure_injector.reset()

    def test_llm_adversarial_modes_graceful_handling(self):
        adversarial_modes = [
            "malformed_json",
            "truncated_json",
            "missing_fields",
            "wrong_types",
            "invalid_enums",
            "empty",
            "prompt_injection",
        ]

        extractor = RequirementsExtractor()
        for mode in adversarial_modes:
            fake = DeterministicLLMFake(default_mode=mode)
            routing_res = fake.route("extraction")

            # Parser must never throw unhandled exception or crash on adversarial input
            parsed = extractor.parse_llm_json(routing_res.text, lead_id="test_lead")
            self.assertIn("requirements", parsed)
            self.assertIn("decisions", parsed)

    def test_requirements_service_resilience_under_message_stream(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            lead_id = lead_factory(crm, name="LLM Chaos Lead")

            res = ril.process_message(
                lead_id=lead_id,
                message="أريد متجر إلكتروني وبوابة دفع وعملة SAR",
                source_message_id="msg_chaos_01",
            )

            self.assertIsInstance(res, dict)
            self.assertIn("total_requirements_count", res)
            self.assertIn("active_decisions", res)
            self.assertEqual(res["active_decisions"].get("currency"), "SAR")

            # Check confidence ranges
            reqs = crm.list_requirements_for_lead(lead_id)
            for r in reqs:
                self.assertGreaterEqual(r["confidence"], 0.0)
                self.assertLessEqual(r["confidence"], 1.0)
                self.assertIn(r["status"], ["captured", "stated", "inferred", "confirmed", "superseded", "rejected"])

    def test_message_replay_idempotency_chaos(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            lead_id = lead_factory(crm, name="Replay Chaos Lead")

            # Execute initial message
            msg = "أريد نظام ويب متكامل مع عملة SAR"
            res1 = ril.process_message(lead_id=lead_id, message=msg, source_message_id="msg-rep-01")
            count1 = res1["total_requirements_count"]
            decs1 = len(res1["active_decisions"])

            # Replay message 10 times consecutively
            for rep in range(10):
                res_rep = ril.process_message(lead_id=lead_id, message=msg, source_message_id="msg-rep-01")
                self.assertEqual(res_rep["total_requirements_count"], count1)
                self.assertEqual(len(res_rep["active_decisions"]), decs1)

            # Assert database has exact canonical count (no duplicate requirements or decisions)
            active_decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(len(active_decs), decs1)

    def test_contradictory_message_stream_handling(self):
        with isolated_db() as db:
            crm = CRMService(db)
            ril = RequirementsService(crm)
            lead_id = lead_factory(crm, name="Contradiction Lead")

            # 1. State SAR
            ril.process_message(lead_id=lead_id, message="العملة المعتمدة هي SAR", source_message_id="m1")
            decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(decs[0]["decision"], "SAR")

            # 2. Change mind to USD
            ril.process_message(lead_id=lead_id, message="غيرت رأيي ونعتمد USD", source_message_id="m2")
            active_decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(len(active_decs), 1)
            self.assertEqual(active_decs[0]["decision"], "USD")

            # All decisions list includes both active and superseded
            all_decs = crm.list_decisions_for_lead(lead_id, status=None)
            self.assertEqual(len(all_decs), 2)


if __name__ == "__main__":
    unittest.main()
