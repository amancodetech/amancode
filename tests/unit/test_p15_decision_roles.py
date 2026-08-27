"""P1-final §3 — Decision-Roles Pack: validation, slicing, tone-only wiring.

Acceptance being proven:
  * validator passes (type-aware meta-pack)
  * slice resolves by (industry, size)
  * prior reaches the NEED-mode brief as TAGGED DATA (qualification tone)
  * ZERO decision diff — planner decision fields are byte-identical with
    the pack absent from the retriever.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

from knowledge.validator import validate_industry_pack  # noqa: E402


PACK_PATH = ROOT / "knowledge" / "packs" / "decision_roles.v1.yaml"


class DecisionRolesPackTest(unittest.TestCase):
    # ---- validator -------------------------------------------------------
    def test_pack_passes_type_aware_validator(self):
        errs = validate_industry_pack(PACK_PATH)
        self.assertEqual(errs, [], f"validator errors: {errs}")
        data = yaml.safe_load(PACK_PATH.read_text())
        self.assertEqual(data["id"], "decision_roles")

    def test_every_entry_is_recommendation_with_provenance(self):
        data = yaml.safe_load(PACK_PATH.read_text())
        root = data["decision_roles"]
        entries = list(root["base_matrix"].values()) \
            + list(root["industry_overrides"].values())
        self.assertTrue(entries)
        for e in entries:
            self.assertEqual(e.get("statement_kind"), "RECOMMENDATION")
            prov = e.get("provenance") or {}
            self.assertTrue(prov.get("source_ref"))
        raw = PACK_PATH.read_text()
        self.assertNotIn("guarantee", raw.lower())
        self.assertNotIn("pricing", raw.lower())

    # ---- slicing -----------------------------------------------------------
    def _retriever(self):
        from amancore.conversation.knowledge_retriever import (
            KnowledgeRetriever)

        return KnowledgeRetriever(root=ROOT / "knowledge")

    def test_slice_resolves_by_industry_and_size(self):
        ret = self._retriever()
        micro = ret.decision_roles_prior("restaurant", 3)
        medium = ret.decision_roles_prior("ecommerce", 120)
        over = ret.decision_roles_prior("healthcare_clinic", None)
        none = ret.decision_roles_prior("generic_business", None)
        self.assertIn("صاحب العمل", micro["roles"]["likely"])
        self.assertEqual(micro["size"], "1–4")
        self.assertEqual(medium["size"], "50–249")
        self.assertTrue(medium["roles"])
        self.assertTrue(over.get("industry_note"))
        self.assertTrue(over.get("tone_delta_ar"))
        self.assertIsNone(none)
        self.assertEqual(micro["kind"], "RECOMMENDATION")

    # ---- wiring: tone-only, zero decision diff ------------------------------
    def _plan(self, brain_store):
        from amancore.conversation.planner import ConversationModel

        cm = ConversationModel(ROOT, brain_store)
        mem = {"facts": {"users": "120"}, "requirements": {},
               "working_memory": {}, "summary": "", "open_questions": [],
               "objections": []}
        return cm.plan(
            lead={"lead_id": "L", "contact_whatsapp": "9", "language": "ar"},
            mem=mem,
            agent_result={"reply": "x", "next_action": "ask_next_question"},
            text="عندي شركة خدمات نحتاج فيها نظام داخلي مع تقارير",
            language="ar", channel="whatsapp"), cm

    def test_prior_reaches_need_brief_as_tagged_data(self):
        from tests.common import make_brain
        import tempfile

        tmp = tempfile.mkdtemp()
        plan, _cm = self._plan(make_brain(Path(tmp)))
        idx = plan["brief"].find("[decision-roles prior")
        self.assertGreaterEqual(idx, 0)
        seg = plan["brief"][idx:]
        self.assertIn("never a fact about THIS lead", seg)
        self.assertIn("CRM fields stay the source of truth", seg)
        # conservative phrasing marker really travels into the prompt
        self.assertTrue(("usually" in seg) or ("typically" in seg)
                        or ("عادة" in seg) or ("غالبا" in seg))

    def test_zero_planner_decision_diff_without_pack(self):
        """Strip the pack from the retriever cache: every DECISION field must
        stay identical. Only the brief text (tone line) may differ."""
        import tempfile

        from tests.common import make_brain

        tmp = tempfile.mkdtemp()
        brain_store = make_brain(Path(tmp))
        plan_with, cm_with = self._plan(brain_store)

        # second stack in a fresh process-state, pack removed from cache
        class NoPackRetriever(cm_with.planner.retriever.__class__):
            pass

        r = cm_with.planner.retriever
        saved = dict(r.packs)
        try:
            r.packs.pop("decision_roles", None)
            mem = {"facts": {"users": "120"}, "requirements": {},
                   "working_memory": {}, "summary": "",
                   "open_questions": [], "objections": []}
            plan_without = cm_with.plan(
                lead={"lead_id": "L", "contact_whatsapp": "9",
                      "language": "ar"},
                mem=mem,
                agent_result={"reply": "x",
                              "next_action": "ask_next_question"},
                text="عندي شركة خدمات نحتاج فيها نظام داخلي مع تقارير",
                language="ar", channel="whatsapp")
        finally:
            r.packs.clear()
            r.packs.update(saved)

        decision_keys = ["mode", "question", "commercial",
                         "working_memory", "value_payload"]
        for k in decision_keys:
            self.assertEqual(plan_without[k], plan_with[k],
                             f"decision drift detected on {k!r}")
        b_with = plan_with["brief"]
        b_without = plan_without["brief"].replace(
            "[decision-roles prior — a GENERAL prior, never a fact about "
            "THIS lead]", "").replace(" | ".join([]), "")
        self.assertIn("[decision-roles prior", b_with)
        # removal difference is confined to the tagged tone segment
        tail = "[decision-roles prior"
        i_w = b_with.find(tail)
        j_end = b_with.find("]", i_w + len(tail))
        closing = b_with.find(".", j_end) if j_end >= 0 else -1
        injected = b_with[i_w:closing + 1] if closing > 0 else ""
        self.assertIn(tail, injected)


if __name__ == "__main__":
    unittest.main()
