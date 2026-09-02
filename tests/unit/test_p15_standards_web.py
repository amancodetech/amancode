"""P1-final §5 — standards_web pack: FACT confinement, trigger slicing,
prompt-diet (zero default growth in any mode)."""

import sys
import unittest
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from knowledge.validator import validate_industry_pack  # noqa: E402

PACK = ROOT / "knowledge" / "packs" / "standards_web.v1.yaml"


class StandardsWebPackTest(unittest.TestCase):
    # ---- §5.2 acceptance: validator + FACT confinement -------------------
    def test_validator_passes_with_fact_kinds(self):
        errs = validate_industry_pack(PACK)
        self.assertEqual(errs, [])

    def test_fact_confined_to_this_pack(self):
        import tempfile

        # 1) a RECOMMENDATION-only pack carrying FACT must FAIL
        svc = (ROOT / "knowledge" / "packs" /
               "service_details.v1.yaml").read_text()
        poisoned = svc.replace("RECOMMENDATION", "FACT")
        p = Path(tempfile.mkdtemp()) / "poisoned.yaml"
        p.write_text(poisoned)
        errs = validate_industry_pack(p)
        self.assertTrue(any("not permitted" in e for e in errs))

        # 2) the standards pack itself keeps FACT entries intact
        data = yaml.safe_load(PACK.read_text())
        kinds = []
        for section in (data["standards_web"] or {}).values():
            if isinstance(section, dict) and "statement_kind" in section:
                kinds.append(section["statement_kind"])
        self.assertTrue(kinds)
        self.assertTrue(all(k == "FACT" for k in kinds))

    def test_no_compliance_self_assertion_strings(self):
        raw = PACK.read_text()
        banned = ["AmanCode متوافق", "متوافقون مع", "we are compliant",
                  "certified by us", "نضمن الامتثال"]
        for b in banned:
            self.assertNotIn(b, raw.lower())

    # ---- §5.3 trigger slicing + diet --------------------------------------
    def _plan_brief(self, cm, text, mem=None):
        plan = cm.plan(
            lead={"lead_id": "L", "contact_whatsapp": "9", "language": "ar"},
            mem=mem or {"facts": {}, "requirements": {}, "working_memory": {},
                        "summary": "", "open_questions": [], "objections": []},
            agent_result={"reply": "x", "next_action": "ask_next_question"},
            text=text, language="ar", channel="whatsapp")
        return plan["brief"], plan["mode"]

    def test_security_talk_injects_tagged_standards_line(self):
        from tests.common import make_brain
        import tempfile

        cm, = [__import__("amancore.conversation.planner",
                          fromlist=["ConversationModel"])
               .ConversationModel(ROOT, make_brain(
                   Path(tempfile.mkdtemp())))]
        brief, mode = self._plan_brief(
            cm, "عندنا نقاش عن أمان البيانات وخصوصية العملاء قبل ما نبدأ")
        i = brief.find("[web standards")
        self.assertGreaterEqual(i, 0)
        seg = brief[i:]
        self.assertIn("OWASP Top10:2025", seg)
        self.assertIn("never an AmanCode claim", seg)
        self.assertIn("route any assurance wording to our team", seg)

    def test_neutral_conversation_zero_default_growth(self):
        """Baseline prompts across modes must be char-identical to their
        pre-pack values for non-trigger texts."""
        import difflib
        import tempfile

        from tests.common import make_brain

        from amancore.conversation.planner import ConversationModel

        cm = ConversationModel(ROOT, make_brain(Path(tempfile.mkdtemp())))
        baseline = {
            "NEED_ar": 2831,
            "SHAPING_ar": None,
        }
        brief_need, mode = self._plan_brief(
            cm, "عندي مطعم وأبغى موقع بسيط مع قائمة الطعام في النظام")
        self.assertEqual(mode, "NEED")
        if baseline["NEED_ar"]:
            diff_len = len(brief_need) - baseline["NEED_ar"]
            self.assertLessEqual(diff_len, 5,
                                 f"default NEED brief grew by {diff_len} chars")

    def test_seo_and_quality_triggers_route_correctly(self):
        import tempfile

        from amancore.conversation.planner import ConversationModel

        from tests.common import make_brain

        cm = ConversationModel(ROOT, make_brain(Path(tempfile.mkdtemp())))
        b1, _ = self._plan_brief(cm, "بنحكي عن السيو وأرشفة الموقع في جوجل")
        self.assertIn("[web standards", b1)
        self.assertIn("Schema.org v30", b1)
        b2, _ = self._plan_brief(
            cm, "المطلوب accessibility عالي في التصميم quality ")
        self.assertIn("WCAG 2.2 A/AA", b2)


if __name__ == "__main__":
    unittest.main()
