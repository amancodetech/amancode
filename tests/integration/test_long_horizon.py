"""Long-horizon certification (20 turns, restart, no live LLM).

Asserts STATE/EVENTS/DB — never wording. Covers: accumulation, deferral
without side effects, unknown-accepted, reference confirm, topic return,
restart continuity, early-fact survival.
"""

import unittest

from tests.common import TempDirTestCase, make_brain, make_db
from tests.integration.test_whatsapp_coordinator import (
    build_coordinator, webhook_body,
)

WA = "551199993"


class LongHorizonTest(TempDirTestCase, unittest.TestCase):
    def _coords(self, db, brain, crm):
        return build_coordinator(db, brain, crm)

    def test_twenty_turns_then_restart(self):
        from amancore.crm.service import CRMService
        db = make_db(str(self.tmp / "long.db"))
        brain = make_brain(self.tmp)
        crm = CRMService(db)
        coord, adapter, *_ = self._coords(db, brain, crm)

        turns = [
            "السلام عليكم",
            "أريد موقعًا لجمعيتي",
            "الموقع تعريفي من 7 صفحات",
            "نحتاجه خلال شهرين",
            "الدفع عبر مدى وبوابات إضافية لاحقًا",
            "الميزانية نتكلم فيها بعدين",
            "we can discuss the price later",
            "أريد شيئًا مثل إير بي إن بي",
            "نعم صحيح",
            "كم سيكلفني؟",
            "تمام",
            "هل تدعمون اللغة الإنجليزية؟",
            "نرجع لموضوع الصفحات",
            "أريد أيضًا متجرًا إلكترونيًا",
            "التطبيق لاحقًا في المرحلة الثانية",
            "لا أعرف موضوع الربط، أجّله",
            "عادي، اقترح أنت",
            "بوابة تبرع إلكترونية",
            "عربي وإنجليزي",
            "بكم الموقع تقريباً؟",
        ]
        for i, t in enumerate(turns[:3]):
            coord.handle_inbound("whatsapp", webhook_body(t, msg_id=f"lh-{i}", wa_id=WA))
        # Stand-in for LLM fact extraction (routerless harness): prior
        # discovery turns yield scope+scale facts (same pattern as
        # test_p03_pricing_tiers._seed_scope).
        lead0 = crm.find_lead_by_whatsapp(WA)
        mem0 = coord.memory.get_or_create(lead0["lead_id"])
        mem0["facts"].update({"scope": "موقع تعريفي 7 صفحات",
                              "timeline": "خلال شهرين"})
        coord.memory.save(mem0)
        for i, t in enumerate(turns[3:8], start=3):
            coord.handle_inbound("whatsapp", webhook_body(t, msg_id=f"lh-{i}", wa_id=WA))
        # Routerless harness has no planner: arrange the planner→coordinator
        # contract (pending reference) directly, then affirm naturally.
        lead8 = crm.find_lead_by_whatsapp(WA)
        mem8 = coord.memory.get_or_create(lead8["lead_id"])
        mem8["working_memory"]["reference_pending"] = "airbnb"
        mem8["working_memory"]["reference_implies"] = ["booking", "payments"]
        coord.memory.save(mem8)
        for i, t in enumerate(turns[8:], start=8):
            coord.handle_inbound("whatsapp", webhook_body(t, msg_id=f"lh-{i}", wa_id=WA))

        lead = crm.find_lead_by_whatsapp(WA)
        self.assertIsNotNone(lead)
        mem = coord.memory.get_or_create(lead["lead_id"])
        facts, wm = mem.get("facts") or {}, mem.get("working_memory") or {}
        # early facts survive to turn 20
        self.assertTrue(facts.get("scope"))
        self.assertTrue(facts.get("timeline"))
        # deferrals recorded, never shape/scale
        acc = set(wm.get("unknown_accepted") or [])
        self.assertIn("budget", acc)
        self.assertNotIn("scope", acc)
        self.assertNotIn("timeline", acc)
        # future tracked, excluded from RIL persistence
        self.assertIn("mobile_app", set(wm.get("future_items") or []))
        reqs = crm.list_requirements_for_lead(lead["lead_id"])
        self.assertNotIn("mobile_app", [r.get("subcategory") for r in reqs])
        # reference confirmed into facts
        self.assertEqual(wm.get("reference_confirmed"), "airbnb")
        # deferral turns created zero approvals on their own: total approvals
        # bounded (only full-gate T2 turns may create them)
        n_approvals = db.execute(
            "SELECT COUNT(*) c FROM approvals WHERE type='final_price'").fetchone()["c"]
        self.assertLessEqual(n_approvals, 3)

        # restart: rebuild everything on the SAME db file
        db.close()
        db2 = make_db(str(self.tmp / "long.db"))
        crm2 = CRMService(db2)
        coord2, *_ = self._coords(db2, brain, crm2)
        lead2 = crm2.find_lead_by_whatsapp(WA)
        self.assertIsNotNone(lead2)
        mem2 = coord2.memory.get_or_create(lead2["lead_id"])
        self.assertTrue((mem2.get("facts") or {}).get("scope"))
        self.assertIn("mobile_app",
                      set((mem2.get("working_memory") or {}).get("future_items") or []))
        coord2.handle_inbound(
            "whatsapp", webhook_body("بكم الموقع تقريباً؟", msg_id="lh-21", wa_id=WA))
        db2.close()


if __name__ == "__main__":
    unittest.main()
