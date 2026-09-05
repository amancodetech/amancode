"""CIR — Contextual Intent Resolution tests.

Pins the deterministic side of CIR (validation, entity/temporal resolution,
policy gate, gate override, ephemerality, planner clarification overlay).
The LLM side is advisory only and enters these tests solely as raw dicts.
"""

from __future__ import annotations

import json
import unittest

from amancore.channels.coordinator import _ExtractionGateRouter
from amancore.conversation import ConversationModel
from amancore.conversation.policy import (
    cir_policy_decision,
    cir_trigger,
    resolve_cir_entity,
    resolve_cir_temporal,
    sanitize_cir_block,
)
from amancore.sales.conversation_memory import ConversationMemory, extract_facts
from tests.common import FakeRouter, TempDirTestCase, make_brain


def _cir(**kw):
    base = {"intent": "pricing", "candidate_target": "project_price",
            "candidate_entity": "project", "candidate_reference": None,
            "candidate_temporal": "now", "ambiguity": False, "confidence": 0.8}
    base.update(kw)
    return base


class SanitizeTests(unittest.TestCase):
    def test_valid_block_passes(self):
        out = sanitize_cir_block(_cir())
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], "pricing")

    def test_non_dict_rejected(self):
        self.assertIsNone(sanitize_cir_block("pricing"))
        self.assertIsNone(sanitize_cir_block(None))
        self.assertIsNone(sanitize_cir_block([]))

    def test_bad_enum_rejected(self):
        self.assertIsNone(sanitize_cir_block(_cir(intent="haggle")))
        self.assertIsNone(sanitize_cir_block(_cir(candidate_target="cheapest")))
        self.assertIsNone(sanitize_cir_block(_cir(candidate_entity="vendor")))
        self.assertIsNone(sanitize_cir_block(_cir(candidate_temporal="someday")))

    def test_confidence_range_and_type(self):
        self.assertIsNone(sanitize_cir_block(_cir(confidence=1.5)))
        self.assertIsNone(sanitize_cir_block(_cir(confidence=-0.1)))
        self.assertIsNone(sanitize_cir_block(_cir(confidence=True)))
        self.assertIsNone(sanitize_cir_block(_cir(confidence="high")))
        self.assertIsNotNone(sanitize_cir_block(_cir(confidence=1.0)))

    def test_non_bool_ambiguity_rejected(self):
        self.assertIsNone(sanitize_cir_block(_cir(ambiguity="yes")))

    def test_non_string_reference_rejected(self):
        self.assertIsNone(sanitize_cir_block(_cir(candidate_reference={"id": 1})))

    def test_missing_fields_defaulted(self):
        out = sanitize_cir_block({})
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], "none")


class TriggerTests(unittest.TestCase):
    def test_pronoun_price_triggers(self):
        self.assertTrue(cir_trigger("كم سعرها؟"))

    def test_in_context_price_triggers(self):
        self.assertTrue(cir_trigger("الموقع كم سعره؟"))

    def test_dialect_price_triggers(self):
        self.assertTrue(cir_trigger("الموقع بشحال؟"))

    def test_short_question_triggers(self):
        self.assertTrue(cir_trigger("و الضمان؟"))

    def test_plain_statement_no_trigger(self):
        self.assertFalse(cir_trigger("أريد موقعا لعرض منتجاتي"))
        self.assertFalse(cir_trigger(""))


class EntityResolutionTests(unittest.TestCase):
    def test_no_cir_is_unknown(self):
        r = resolve_cir_entity(None, explicit=[], active_category="website")
        self.assertEqual(r["status"], "unknown")

    def test_single_explicit_resolves(self):
        r = resolve_cir_entity(_cir(), explicit=["website"],
                               active_category=None)
        self.assertEqual((r["status"], r["entity"]), ("resolved", "project"))
        self.assertEqual(r["evidence_source"], "explicit_current")

    def test_two_explicit_is_ambiguous(self):
        r = resolve_cir_entity(_cir(), explicit=["website", "ecommerce"],
                               active_category="website")
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(len(r["competing_candidates"]), 2)

    def test_active_category_supports_project(self):
        r = resolve_cir_entity(_cir(), explicit=[],
                               active_category="website")
        self.assertEqual((r["status"], r["entity"]), ("resolved", "project"))
        self.assertEqual(r["evidence_strength"], "supported")

    def test_no_evidence_is_unknown(self):
        r = resolve_cir_entity(_cir(), explicit=[], active_category=None)
        self.assertEqual(r["status"], "unknown")

    def test_llm_ambiguity_flag_respected(self):
        r = resolve_cir_entity(_cir(ambiguity=True), explicit=["website"],
                               active_category="website")
        self.assertEqual(r["status"], "ambiguous")

    def test_product_candidate_without_verified_product_is_ambiguous(self):
        # Forbidden inference: category absence + product wording != product.
        r = resolve_cir_entity(_cir(candidate_entity="product",
                                    candidate_target="product_item_price"),
                               explicit=[], active_category=None)
        self.assertEqual(r["status"], "ambiguous")

    def test_candidate_alone_never_resolves(self):
        r = resolve_cir_entity(_cir(candidate_entity="project"), explicit=[],
                               active_category=None)
        self.assertNotEqual(r["status"], "resolved")


class TemporalTests(unittest.TestCase):
    def test_pricing_without_cues_is_now(self):
        self.assertEqual(resolve_cir_temporal(_cir(), "كم سعر الموقع؟"), "now")

    def test_later_cue_defers(self):
        self.assertEqual(
            resolve_cir_temporal(_cir(), "السعر نتكلم عنه لاحقًا"), "later")

    def test_phase2_cue(self):
        self.assertEqual(
            resolve_cir_temporal(_cir(), "التطبيق في المرحلة الثانية"),
            "phase2")

    def test_deterministic_cue_beats_candidate(self):
        self.assertEqual(
            resolve_cir_temporal(_cir(candidate_temporal="now"),
                                 "نناقش السعر later"), "later")

    def test_timeline_intent_never_now(self):
        self.assertNotEqual(
            resolve_cir_temporal(_cir(intent="timeline"), "كم سيأخذ المشروع؟"),
            "now")


class PolicyGateTests(unittest.TestCase):
    def _ent(self, status="resolved", entity="project"):
        return {"status": status, "entity": entity,
                "evidence_source": "explicit_current",
                "evidence_strength": "explicit", "competing_candidates": []}

    def test_enter_on_resolved_project_now(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=_cir(),
                                entity=self._ent(), temporal="now")
        self.assertEqual(d, "ENTER_PRICING")

    def test_legacy_fallback_without_interpretation(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=None,
                                entity=self._ent("unknown", None),
                                temporal="unknown")
        self.assertEqual(d, "ENTER_PRICING")

    def test_mention_without_cir_continues(self):
        d = cir_policy_decision(price_intent="mention", cir=None,
                                entity=self._ent("unknown", None),
                                temporal="unknown")
        self.assertEqual(d, "CONTINUE_DISCOVERY")

    def test_ambiguous_clarifies(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=_cir(),
                                entity=self._ent("ambiguous", None),
                                temporal="now")
        self.assertEqual(d, "CLARIFY")

    def test_unknown_with_cir_clarifies(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=_cir(),
                                entity=self._ent("unknown", None),
                                temporal="now")
        self.assertEqual(d, "CLARIFY")

    def test_support_veto_denies_despite_confidence_10(self):
        d = cir_policy_decision(price_intent="direct_ask",
                                cir=_cir(confidence=1.0),
                                entity=self._ent(), temporal="now",
                                domain_intent="support")
        self.assertEqual(d, "DENY")

    def test_scope_review_denies(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=_cir(),
                                entity=self._ent(), temporal="now",
                                scope_under_review=True)
        self.assertEqual(d, "DENY")

    def test_later_defers_to_discovery(self):
        d = cir_policy_decision(price_intent="direct_ask", cir=_cir(),
                                entity=self._ent(), temporal="later")
        self.assertEqual(d, "CONTINUE_DISCOVERY")

    def test_timeline_intent_continues(self):
        d = cir_policy_decision(
            price_intent="mention", cir=_cir(intent="timeline",
                                             candidate_target="project_timeline"),
            entity=self._ent(), temporal="unknown")
        self.assertEqual(d, "CONTINUE_DISCOVERY")

    def test_deferral_continues(self):
        d = cir_policy_decision(price_intent="deferral", cir=None,
                                entity=self._ent("unknown", None),
                                temporal="unknown")
        self.assertEqual(d, "CONTINUE_DISCOVERY")

    def test_confidence_never_read(self):
        # identical inputs except confidence must give identical decisions
        kw = dict(price_intent="direct_ask", entity=self._ent(),
                  temporal="now")
        self.assertEqual(cir_policy_decision(cir=_cir(confidence=0.01), **kw),
                         cir_policy_decision(cir=_cir(confidence=1.0), **kw))


class GateForceTests(unittest.TestCase):
    def _gate(self, **kw):
        from amancore.conversation.policy import ConversationPolicy
        inner = FakeRouter({})
        return _ExtractionGateRouter(inner, text="الموقع كم سعره؟",
                                     policy=ConversationPolicy(),
                                     wm={"industry": "restaurant"}, **kw)

    def test_confident_picture_skips_by_default(self):
        g = self._gate()
        g.route("extraction", [{"role": "user", "content": "x"}])
        self.assertTrue(g.skipped)

    def test_force_disables_skip(self):
        g = self._gate(force=True)
        res = g.route("extraction", [{"role": "user", "content": "x"}])
        self.assertFalse(g.skipped)
        self.assertEqual(res.text, "{}")


class EphemeralTests(unittest.TestCase):
    def test_cir_carried_raw_but_never_merged(self):
        payload = {"scope": "site", "cir": _cir()}
        router = FakeRouter({"extraction": json.dumps(payload, ensure_ascii=False)})
        facts = extract_facts("كم سعر الموقع؟", router)
        self.assertEqual(facts.get("scope"), "site")
        self.assertIsInstance(facts.get("cir"), dict)
        mem = {"facts": {}, "open_questions": []}
        ConversationMemory(crm=None).merge_facts(mem, facts)
        self.assertNotIn("cir", mem["facts"])
        self.assertEqual(mem["facts"].get("scope"), "site")

    def test_no_router_no_cir(self):
        facts = extract_facts("كم سعر الموقع؟", None)
        self.assertNotIn("cir", facts)


class PlannerClarifyTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        TempDirTestCase.setUp(self)
        self.brain = make_brain(self.tmp)
        self.model = ConversationModel(self.tmp, self.brain)

    def test_clarify_decision_adds_single_question(self):
        cir = {"decision": "CLARIFY",
               "entity": {"status": "ambiguous", "entity": None,
                          "competing_candidates": ["website", "ecommerce"]},
               "temporal": "now", "cir": _cir()}
        plan = self.model.plan(lead={"lead_id": "L1", "industry": None},
                               mem={"facts": {}}, agent_result={}, text="كم سعرها؟",
                               language="ar", channel="whatsapp", cir=cir)
        self.assertEqual((plan.get("question") or {}).get("field"), "_cir_clarify")
        self.assertIn("EXACTLY ONE", plan.get("brief") or "")

    def test_no_cir_leaves_plan_unchanged(self):
        plan = self.model.plan(lead={"lead_id": "L1", "industry": None},
                               mem={"facts": {}}, agent_result={}, text="كم سعرها؟",
                               language="ar", channel="whatsapp")
        self.assertNotEqual((plan.get("question") or {}).get("field"), "_cir_clarify")


if __name__ == "__main__":
    unittest.main()
