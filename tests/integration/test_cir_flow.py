"""CIR end-to-end: interpretation -> deterministic gate -> pricing branch.

Differential design: every price message below is legacy `direct_ask`
(verified), so any diversion from the pricing branch is caused ONLY by CIR.
"""

import json
import unittest

from amancore.conversation import ConversationModel
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db
from tests.integration.test_whatsapp_coordinator import (
    build_coordinator, webhook_body, WA_ID,
)


class _Out:
    def __init__(self, text="تم"):
        self.text = text


class CaptureDrafter:
    def __init__(self):
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return _Out()


def _extraction_router(cir: dict | None):
    payload = {"scope": "mentioned"}
    if cir is not None:
        payload["cir"] = cir
    return FakeRouter({"extraction": json.dumps(payload, ensure_ascii=False)})


def _cir(intent="pricing", target="project_price", entity="project",
         temporal="now", ambiguity=False, confidence=0.85):
    return {"intent": intent, "candidate_target": target,
            "candidate_entity": entity, "candidate_reference": None,
            "candidate_temporal": temporal, "ambiguity": ambiguity,
            "confidence": confidence}


class CirFlowTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        from amancore.crm.service import CRMService
        self.crm = CRMService(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _coord(self, router):
        coord, adapter, outbox, crm, audit = build_coordinator(
            self.db, self.brain, self.crm, router=router)
        coord.conversation = ConversationModel(self.tmp, self.brain)
        coord._drafter = CaptureDrafter()
        return coord, adapter, router

    def _price_rows(self):
        return self.db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE idempotency_key LIKE '%out:price:%'"
        ).fetchone()["c"]

    def test_ambiguous_pronoun_clarifies_no_pricing_branch(self):
        router = _extraction_router(_cir(entity="unknown", target="unknown",
                                         ambiguity=True))
        coord, adapter, _ = self._coord(router)
        coord.handle_whatsapp_webhook(webhook_body("كم سعرها؟", msg_id="cir-1"))
        # legacy would ENTER (direct_ask); CIR must divert to clarification
        self.assertEqual(self._price_rows(), 0)
        sent = adapter.provider.sent[-1]["payload"]
        self.assertTrue(sent.strip())
        # T0/CLARIFY replies carry zero authorized figures
        self.assertNotRegex(sent, r"\d{4,}")

    def test_resolved_project_enters_pricing_branch(self):
        router = _extraction_router(_cir())
        coord, adapter, _ = self._coord(router)
        coord.handle_whatsapp_webhook(
            webhook_body("كم سعر الموقع؟", msg_id="cir-2"))
        self.assertEqual(self._price_rows(), 1)
        sent = adapter.provider.sent[-1]["payload"]
        self.assertTrue(sent.strip())

    def test_hostile_llm_cannot_force_pricing_on_deferral(self):
        router = _extraction_router(_cir(confidence=1.0))
        coord, adapter, _ = self._coord(router)
        coord.handle_whatsapp_webhook(
            webhook_body("we can discuss the price later", msg_id="cir-3"))
        self.assertEqual(self._price_rows(), 0)
        sent = adapter.provider.sent[-1]["payload"]
        self.assertTrue(sent.strip())

    def test_gate_force_reaches_llm_despite_confident_picture(self):
        router = _extraction_router(_cir())
        coord, adapter, router = self._coord(router)
        coord.handle_whatsapp_webhook(
            webhook_body("موقع لمطعم شاورما", msg_id="cir-4a"))
        router.calls.clear()
        # industry now known + single category + no digits: the gate would
        # skip this without the CIR trigger (price wording forces the call)
        coord.handle_whatsapp_webhook(
            webhook_body("الموقع كم سعره؟", msg_id="cir-4b"))
        tasks = [c[0] for c in router.calls]
        self.assertIn("extraction", tasks)
        self.assertEqual(self._price_rows(), 1)


if __name__ == "__main__":
    unittest.main()
