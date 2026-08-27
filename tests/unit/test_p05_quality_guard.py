"""P0-5 — QualityGuard v1: planned sales turns obey their ResponsePlan."""

from __future__ import annotations

import unittest

from amancore.channels.coordinator import MessageCoordinator  # noqa: F401 wiring
from amancore.conversation.quality_guard import QualityGuard
from tests.common import TempDirTestCase


def _plan(mode="NEED", language="ar", allowed=None, foreign=None, mode_budget=False):
        return {
            "mode": mode,
            "language": language,
            "quality": {
                "allowed_numbers": allowed or [],
                "forbidden_catalog_names": foreign or ["Mobile App"],
                "forbidden_claims": [],
            },
        }


class GuardUnitTests(unittest.TestCase):
    def setUp(self):
        self.g = QualityGuard()

    def test_passes_when_nothing_violates(self):
        verdict = self.g.check(
            "أهلاً! مقترحنا يشمل: الرئيسية | من نحن | برامجنا. ما الجزء الأهم عندكم؟",
            plan=_plan())
        self.assertTrue(verdict["allowed"], verdict)

    def test_unauthorized_number_blocked_then_allowed(self):
        bad = self.g.check("التقدير حوالي 5000 USD", plan=_plan(allowed=["4000", "6000"]))
        self.assertFalse(bad["allowed"])
        good = self.g.check("النطاق التقديري 4000 إلى 6000 USD",
                            plan=_plan(allowed=["4000", "6000"], mode="COMMERCIAL"))
        self.assertTrue(good["allowed"])

    def test_foreign_service_name_blocked(self):
        verdict = self.g.check("نرشح لك تطبيق Mobile App لجمعيتك", plan=_plan())
        self.assertFalse(verdict["allowed"])

    def test_forbidden_claim_blocked(self):
        verdict = self.g.check("نضمن لك زيادة التبرعات 100%!",
                               plan=_plan(foreign=[]))
        self.assertFalse(verdict["allowed"])

    def test_question_budget(self):
        two = self.g.check("ما رأيك؟ وهل تودين المتابعة؟", plan=_plan())
        self.assertFalse(two["allowed"])
        one = self.g.check("ما الجزء الأهم عندكم؟", plan=_plan())
        self.assertTrue(one["allowed"])

    def test_language_mismatch_arabic_customer(self):
        verdict = self.g.check("Sure! We can start right away.", plan=_plan(language="ar"))
        self.assertFalse(verdict["allowed"])

    def test_budget_ask_outside_commercial(self):
        verdict = self.g.check("كم الميزانية المتاحة لديكم؟", plan=_plan(mode="NEED"))
        self.assertFalse(verdict["allowed"])

    def test_echo_customer_blocked(self):
        long_msg = "عندنا جمعية خيرية كبيرة في صنعاء نحتاج موقع شامل للتبرعات والمتطوعين والتقارير"
        verdict = self.g.check(f"{long_msg} — فهمتك!", plan=_plan(),
                               last_customer_text=long_msg)
        self.assertFalse(verdict["allowed"])

    def test_legacy_path_bypasses_guard(self):
        verdict = self.g.check("أي شيء فيه أرقام 9999 وميزانية؟؟", plan=None)
        self.assertTrue(verdict["allowed"])

    def test_wrong_currency_blocked_when_declared(self):
        plan = _plan(mode="COMMERCIAL")
        plan["quality"]["allowed_numbers"] = ["4000", "6000"]
        plan["commercial"] = {"tier": "T1", "currency": "USD"}
        ok = self.g.check("النطاق التقديري 4000 إلى 6000 USD",
                          plan=plan)
        self.assertTrue(ok["allowed"], ok)
        bad = self.g.check("النطاق من 4000 إلى 6000 SAR",
                           plan=plan)
        self.assertFalse(bad["allowed"])

    def test_estimate_worded_as_final_quote_blocked(self):
        plan = _plan(mode="COMMERCIAL")
        plan["quality"]["allowed_numbers"] = ["4000"]
        plan["commercial"] = {"tier": "T2", "currency": "USD"}
        verdict = self.g.check("هذا السعر النهائي هو 4000 دولار",
                               plan=plan)
        self.assertFalse(verdict["allowed"])
        self.assertTrue(any("estimate_worded_as_final" in v
                            for v in verdict["violations"]))


if __name__ == "__main__":
    unittest.main()
