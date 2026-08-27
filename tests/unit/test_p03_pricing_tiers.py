"""P0-3 — Pricing tiers T0–T3 wired end-to-end.

Engine alias fix · Gate-B gating · deterministic T2 estimate · owner-only
approval · frozen T3 snapshot reachable by the existing price-intent path.
"""

from __future__ import annotations

import json
import unittest

from amancore.business_brain.store import BrainStore
from amancore.channels.coordinator import MessageCoordinator
from amancore.conversation import ConversationModel
from amancore.conversation.policy import ConversationPolicy
from amancore.conversation.pricing_flow import QuoteFlow
from amancore.crm.service import CRMService
from amancore.pricing.engine import PricingEngine
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.sales.conversation_memory import ConversationMemory
from tests.common import ROOT, TempDirTestCase, make_brain, make_db

PRICE_MSG = "بكم الموقع تقريباً؟"


def _brain_real(tmp):
    return make_brain(tmp)


class EngineAliasTests(TempDirTestCase, unittest.TestCase):
    def test_service_ids_map_to_policy_keys(self):
        store = BrainStore(ROOT / "amancore" / "business_brain")
        engine = PricingEngine(store)
        result = engine.price({"service": "business_website_system",
                               "estimated_hours": 20, "market": "gcc",
                               "risk_level": "medium"})
        self.assertEqual(result["breakdown"]["markup"], 2.5)
        self.assertEqual(result["breakdown"]["minimum_multiplier"], 1.30)
        self.assertLess(result["negotiation_floor"], result["target_price"])


class QuoteFlowTests(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.brain = make_brain(self.tmp)
        self.db = make_db(self.tmp / "q.db")
        self.crm = CRMService(self.db)
        self.alerts = []
        self.flow = QuoteFlow(self.db, self.crm, self.brain,
                              PricingSnapshotStore(self.db),
                              dispatcher=None,
                              owner_alert=lambda level, msg, corr, **kw:
                                  self.alerts.append(msg))
        self.lead_id = self.crm.create_lead(source_channel="whatsapp",
                                            contact_whatsapp="551100010")
        self.lead = self.crm.get_lead(self.lead_id)

    def test_gate_b_matrix(self):
        policy = ConversationPolicy()
        self.assertFalse(QuoteFlow.gate_b_ready(policy, None, {}))
        self.assertFalse(QuoteFlow.gate_b_ready(policy, "website", {}))
        self.assertFalse(QuoteFlow.gate_b_ready(
            policy, "website", {"scope": "pages only"}))          # no timeline/scale
        self.assertTrue(QuoteFlow.gate_b_ready(
            policy, "website", {"scope": "pages", "timeline": "next month"}))

    def test_estimate_gcc_currency_and_range(self):
        est = self.flow.estimate({"language": "ar"}, "website")
        self.assertIsNotNone(est)
        self.assertEqual(est["currency"], "USD")
        self.assertLess(est["low"], est["high"])
        self.assertGreater(est["high"], 0)

    def test_approval_request_then_finalize_creates_snapshot(self):
        est = self.flow.estimate({"language": "ar"}, "website")
        approval_id = self.flow.request_owner_approval(self.lead, est)
        pending = self.flow.pending()
        self.assertEqual(len(pending), 1)
        self.assertIn("/qapprove", self.alerts[0])
        payload = json.loads(self.flow.approvals.get(approval_id)["payload"])
        self.assertEqual(payload["proposed_price"], est["high"])
        # owner approves via console path
        snapshot_id = self.flow.finalize(approval_id, approved_by="owner_console")
        opp_id = payload["opportunity_id"]
        snap = self.flow.snapshots.get_for_opportunity(opp_id)
        self.assertIsNotNone(snap)
        self.assertEqual(float(snap["approved_price"]), est["high"])
        self.assertEqual(snap["currency"], est["currency"])
        # double-finalize is rejected
        with self.assertRaises(ValueError):
            self.flow.finalize(approval_id, approved_by="owner_console")
        return opp_id, snap


class CoordinatorPricingTests(TempDirTestCase, unittest.TestCase):
    """Price-intent behavior through handle_inbound for T0/T2/T3."""

    def _build(self):
        from amancore.agents.sales import SalesAgent
        from amancore.channels.handover import HandoverService
        from amancore.channels.language import LanguageDetector
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from amancore.channels.response_filter import ExternalResponseFilter
        from amancore.channels.whatsapp import WhatsAppAdapter
        from amancore.ops.cost_governor import CostGovernor
        from amancore.pricing.proposal import ProposalStore
        from amancore.sales.discovery import DiscoveryEngine
        from amancore.sales.followup import FollowupEngine
        from amancore.sales.handoff import HandoffService
        from amancore.sales.qualification import QualificationEngine
        from amancore.services.audit import AuditService
        from amancore.services.events import EventDispatcher, IdempotencyStore
        from amancore.skills.localization import LocalizationSkill
        from amancore.skills.objection_handling import ObjectionHandlingSkill

        class Cap:
            def __init__(self):
                self.messages = []

            def complete(self, messages):
                self.messages.append(messages)

                class _O:
                    text = "تم"

                return _O()

        db = make_db(self.tmp / "cp.db")
        brain = make_brain(self.tmp)
        audit = AuditService(db)
        dispatcher = EventDispatcher()
        adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        outbox = MessageOutbox(db)
        chpolicy = ChannelPolicyEngine(brain)
        worker = OutboxWorker(outbox, {"whatsapp": adapter}, chpolicy,
                              audit=audit, dispatcher=dispatcher)
        crm = CRMService(db)
        memory = ConversationMemory(crm)
        alerts = []
        quote_flow = QuoteFlow(db, crm, brain, PricingSnapshotStore(db),
                               dispatcher=None,
                               owner_alert=lambda l, m, c, **k: alerts.append(m),
                               audit=audit)
        sales = SalesAgent(brain, crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(brain),
                           FollowupEngine(), HandoffService(dispatcher),
                           audit=audit, dispatcher=dispatcher)
        coord = MessageCoordinator(
            adapter, outbox, worker, sales, crm, memory,
            HandoverService(crm, dispatcher), ExternalResponseFilter(), chpolicy,
            IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(db), ProposalStore(db),
            owner_alert=lambda *a, **k: None,
            audit=audit, dispatcher=dispatcher,
            conversation=ConversationModel(self.tmp, brain),
            quote_flow=quote_flow,
            cost_governor=CostGovernor({}))
        drafter = Cap()
        coord._drafter = drafter
        return coord, drafter, db, crm, quote_flow, alerts

    @staticmethod
    def _body(text, msg_id, wa="551100099"):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"wa_id": wa}],
                    "messages": [{"from": wa, "id": msg_id, "type": "text",
                                  "text": {"body": text}}]}}]}]}

    def _seed_scope(self, crm, lead_id):
        mem = ConversationMemory(crm).get_or_create(lead_id)
        mem["facts"].update({"scope": "7 صفحات مع بوابة تبرع",
                             "timeline": "خلال شهرين"})
        ConversationMemory(crm).save(mem)

    def test_t2_estimate_with_approval_request(self):
        coord, drafter, db, crm, flow, alerts = self._build()
        coord.handle_inbound("whatsapp", self._body(
            "أريد موقع لجمعية", "m1"))
        self._seed_scope(crm, crm.get_lead_by_identity_whatsapp("551100099")["lead_id"]
                         if hasattr(crm, "get_lead_by_identity_whatsapp") else
                         self._lead_id_via_row(db))
        drafter.messages.clear()
        summary = coord.handle_inbound("whatsapp", self._body(PRICE_MSG, "m2"))
        self.assertEqual(summary["processed"], 1)
        prompt = str(drafter.messages[-1])
        self.assertIn("TENTATIVE ESTIMATE ONLY", prompt)
        self.assertIn("tier=T2", prompt)
        self.assertEqual(len(flow.pending()), 1)
        self.assertTrue(alerts)

    def test_t0_deferral_when_scope_missing(self):
        coord, drafter, _db, _crm, flow, _alerts = self._build()
        coord.handle_inbound("whatsapp", self._body(PRICE_MSG, "m1"))
        self.assertEqual(len(flow.pending()), 0)          # no approval requested
        prompt = str(drafter.messages[0])
        self.assertNotIn("TENTATIVE ESTIMATE", prompt)

    def test_t3_approved_snapshot_short_circuits_llm(self):
        coord, drafter, db, crm, flow, _alerts = self._build()
        wa = "551100099"
        coord.handle_inbound("whatsapp", self._body("مرحبا", "m0"))
        lead_id = db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (wa,)).fetchone()["lead_id"]
        est = flow.estimate({"language": "ar"}, "website")
        aid = flow.request_owner_approval(crm.get_lead(lead_id), est)
        flow.finalize(aid, approved_by="owner_console")
        drafter.messages.clear()
        summary = coord.handle_inbound("whatsapp", self._body(PRICE_MSG, "m2"))
        # T3 short-circuit: deterministic approved-price reply, LLM bypassed,
        # and no duplicate approval request.
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(drafter.messages, [])
        self.assertEqual(len(flow.pending()), 0)

    def _lead_id_via_row(self, db):
        return db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id='551100099'"
        ).fetchone()["lead_id"]

    def test_scope_change_supersedes_approved_snapshot(self):
        coord, drafter, db, crm, flow, _alerts = self._build()
        wa = "551100099"
        coord.handle_inbound("whatsapp", self._body("مرحبا", "m0"))
        lead_id = db.execute(
            "SELECT lead_id FROM platform_identities WHERE external_user_id=?",
            (wa,)).fetchone()["lead_id"]
        self._seed_scope(crm, lead_id)  # facts: 7 pages, بوابة تبرع, timeline
        wm_mem = ConversationMemory(crm).get_or_create(lead_id)
        wm_mem["working_memory"] = {"service_category": "website"}
        ConversationMemory(crm).save(wm_mem)
        est = flow.estimate({"language": "ar"}, "website")
        from amancore.pricing import registry
        fp = registry.scope_fingerprint(
            "website", {"scope": "7 صفحات مع بوابة تبرع",
                        "timeline": "خلال شهرين"}, False)
        aid = flow.request_owner_approval(crm.get_lead(lead_id), est,
                                          scope_fingerprint=fp)
        flow.finalize(aid, approved_by="owner_console")
        drafter.messages.clear()
        # Same scope -> deterministic short-circuit, no LLM
        summary = coord.handle_inbound("whatsapp", self._body(PRICE_MSG, "m2"))
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(drafter.messages, [])
        # Scope changed (15 pages) -> old snapshot superseded, new estimate path
        mem = ConversationMemory(crm).get_or_create(lead_id)
        mem["facts"].update({"scope": "15 صفحات", "timeline": "خلال شهرين"})
        ConversationMemory(crm).save(mem)
        drafter.messages.clear()
        coord.handle_inbound("whatsapp", self._body(PRICE_MSG, "m3"))
        self.assertTrue(drafter.messages, "scope change must re-engage pricing")
        opp = crm.get_opportunity_for_lead(lead_id)
        snap = flow.snapshots.get_for_opportunity(opp["opportunity_id"])
        self.assertIsNone(snap)  # the old snapshot is no longer active


if __name__ == "__main__":
    unittest.main()
