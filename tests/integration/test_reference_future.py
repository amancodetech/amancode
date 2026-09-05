"""D5 reference-confirm + D6 future-scope (planner + coordinator)."""

import unittest

from amancore.business_brain.store import BrainStore
from amancore.conversation import ConversationModel
from tests.common import ROOT, TempDirTestCase, make_brain, make_db


class ReferenceConfirmTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.model = ConversationModel(ROOT, BrainStore(ROOT / "amancore" / "business_brain"))

    def test_reference_asks_confirm_not_facts(self):
        plan = self.model.plan(
            lead={"lead_id": "L"},
            mem={"facts": {"scope": "مطعم"},
                 "working_memory": {"mode": "SHAPING",
                                    "service_category": "website"}},
            agent_result={}, text="أريد شيئًا مثل إير بي إن بي",
            language="ar", channel="whatsapp")
        self.assertEqual(plan["question"]["field"], "reference_confirm")
        self.assertEqual(plan["working_memory"]["reference_pending"], "airbnb")
        # nothing confirmed yet
        self.assertNotIn("reference_confirmed", plan["working_memory"])

    def test_reference_ask_bounded(self):
        wm = {"mode": "SHAPING", "service_category": "website",
              "reference_pending": "noon",
              "reference_implies": ["ecommerce"], "reference_asks": 2}
        plan = self.model.plan(
            lead={"lead_id": "L"}, mem={"facts": {}, "working_memory": wm},
            agent_result={}, text="أريد موقعًا", language="ar",
            channel="whatsapp")
        self.assertNotIn("reference_pending", plan["working_memory"])


class FutureExclusionTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        from amancore.crm.service import CRMService
        self.crm = CRMService(self.db)
        from tests.integration.test_whatsapp_coordinator import build_coordinator
        self.coord, self.adapter, *_ = build_coordinator(
            self.db, self.brain, self.crm)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_future_mobile_excluded_from_ril_and_facts(self):
        from tests.integration.test_whatsapp_coordinator import webhook_body
        self.coord.handle_inbound(
            "whatsapp", webhook_body("نريد تطبيق جوال لاحقًا في المرحلة الثانية",
                                     msg_id="f1", wa_id="551199991"))
        lead = self.crm.find_lead_by_whatsapp("551199991")
        mem = self.coord.memory.get_or_create(lead["lead_id"])
        self.assertIn("mobile_app", (mem.get("working_memory") or {}).get("future_items", []))
        reqs = self.crm.list_requirements_for_lead(lead["lead_id"])
        self.assertNotIn("mobile_app", [r.get("subcategory") for r in reqs])

    def test_affirmation_confirms_pending_reference(self):
        # Planner ask-step is covered at unit level; here the harness has no
        # conversation model, so the planner→coordinator contract (pending in
        # working memory) is arranged directly, then affirmed.
        from tests.integration.test_whatsapp_coordinator import webhook_body
        wa = "551199992"
        self.coord.handle_inbound(
            "whatsapp", webhook_body("أريد شيئًا مثل إير بي إن بي", msg_id="r1", wa_id=wa))
        lead = self.crm.find_lead_by_whatsapp(wa)
        mem = self.coord.memory.get_or_create(lead["lead_id"])
        mem["working_memory"]["reference_pending"] = "airbnb"
        mem["working_memory"]["reference_implies"] = ["booking", "payments"]
        self.coord.memory.save(mem)
        self.coord.handle_inbound(
            "whatsapp", webhook_body("نعم صحيح", msg_id="r2", wa_id=wa))
        mem2 = self.coord.memory.get_or_create(lead["lead_id"])
        facts = mem2.get("facts") or {}
        self.assertTrue(facts.get("booking"))
        self.assertIn("airbnb", (facts.get("scope") or ""))
        self.assertEqual((mem2.get("working_memory") or {}).get("reference_confirmed"),
                         "airbnb")


if __name__ == "__main__":
    unittest.main()
