"""P1-2 — Latency architecture: deterministic tests only.

Covers §2 extraction gating, §3 prompt diet, §4 typing hook, §5 first-pass
metrics and §6 type-aware validator. No LLM is ever contacted: routers are
counting stubs.
"""

import json
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests.common import TempDirTestCase, make_brain, make_db  # noqa: E402

from amancore.agents.sales import SalesAgent  # noqa: E402
from amancore.channels.coordinator import MessageCoordinator  # noqa: E402
from amancore.channels.handover import HandoverService  # noqa: E402
from amancore.channels.language import LanguageDetector  # noqa: E402
from amancore.channels.outbox import MessageOutbox, OutboxWorker  # noqa: E402
from amancore.channels.policy import ChannelPolicyEngine  # noqa: E402
from amancore.channels.response_filter import ExternalResponseFilter  # noqa: E402
from amancore.channels.telegram import TelegramAdapter  # noqa: E402
from amancore.channels.whatsapp import WhatsAppAdapter  # noqa: E402
from amancore.conversation.knowledge_retriever import (  # noqa: E402
    KnowledgeRetriever,
)
from amancore.conversation.planner import ConversationModel  # noqa: E402
from amancore.crm.service import CRMService  # noqa: E402
from amancore.pricing.proposal import ProposalStore  # noqa: E402
from amancore.pricing.snapshot import PricingSnapshotStore  # noqa: E402
from amancore.sales.conversation_memory import ConversationMemory  # noqa: E402
from amancore.sales.discovery import DiscoveryEngine  # noqa: E402
from amancore.sales.followup import FollowupEngine  # noqa: E402
from amancore.sales.handoff import HandoffService as HandSvc  # noqa: E402
from amancore.sales.qualification import QualificationEngine  # noqa: E402
from amancore.services.events import (EventDispatcher,  # noqa: E402
                                      IdempotencyStore)
from amancore.skills.localization import LocalizationSkill  # noqa: E402
from amancore.skills.objection_handling import (  # noqa: E402
    ObjectionHandlingSkill,
)
from knowledge.validator import validate_industry_pack  # noqa: E402


WA = f"6288{uuid.uuid4().hex[:8]}"


class _CountingRouter:
    """Records every routed task_class; returns canned JSON/text."""

    def __init__(self):
        self.calls = []

    def route(self, task_class, messages, **kw):
        self.calls.append(task_class)
        if task_class == "extraction":
            return SimpleNamespace(text="{}")
        return SimpleNamespace(text="تم")


class P12LatencyArchitecture(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.wa_adapter = WhatsAppAdapter({"mode": "mock",
                                           "signature_required": False})
        self.tg_adapter = TelegramAdapter({"mode": "mock"})
        self.outbox = MessageOutbox(self.db)
        policy = ChannelPolicyEngine(self.brain)
        self.worker = OutboxWorker(
            self.outbox,
            {"whatsapp": self.wa_adapter, "telegram": self.tg_adapter},
            policy, dispatcher=self.dispatcher)
        memory = ConversationMemory(self.crm)
        self.router = _CountingRouter()
        sales = SalesAgent(
            self.brain, self.crm, memory, DiscoveryEngine(),
            QualificationEngine(),
            ObjectionHandlingSkill(self.brain), FollowupEngine(),
            HandSvc(self.dispatcher),
            router=self.router, dispatcher=self.dispatcher,
        )
        from amancore.routing.models import ROUTINE
        self.coord = MessageCoordinator(
            {"whatsapp": self.wa_adapter, "telegram": self.tg_adapter},
            self.outbox, self.worker, sales, self.crm,
            memory, HandoverService(self.crm, self.dispatcher),
            ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(),
            LocalizationSkill(router=None),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda level, msg, corr, **kw: None,
            dispatcher=self.dispatcher,
            conversation=ConversationModel(ROOT / "knowledge", self.brain),
            cost_governor=SimpleNamespace(
                allow=lambda key: (True, "ok"),
                record=lambda key, **kw: None))
        # route drafts through the counting router (no external LLM ever)
        self.coord._router = (self.router, ROUTINE)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    # ---- §2 extraction gating ------------------------------------------
    def test_typical_message_skips_extraction_llm(self):
        body = self._body("عندي مطعم وأبغى موقع بسيط مع قائمة الطعام")
        self.coord.handle_inbound("whatsapp", body)
        extractions = [c for c in self.router.calls if c == "extraction"]
        drafts = [c for c in self.router.calls if c != "extraction"]
        self.assertEqual(extractions, [],
                         "typical deterministic scenario must skip the "
                         "extraction LLM call")
        self.assertEqual(len(drafts), 1, "exactly one draft call remains")

    def test_ambiguous_message_keeps_extraction_llm(self):
        body = self._body("ربما أفكر بشيء، ما رأيكم؟ كم التكلفة عادةً؟")
        self.coord.handle_inbound("whatsapp", body)
        self.assertEqual([c for c in self.router.calls if c == "extraction"],
                         ["extraction"])

    def test_scope_negation_never_gates_out(self):
        self.coord.handle_inbound("whatsapp",
                                  self._body("عندي مطعم وأبغى موقع بسيط"))
        before = len(self.router.calls)
        self.coord.handle_inbound("whatsapp",
                                  self._body("لا لا ما أبغى الحجز أبداً"))
        late = [c for c in self.router.calls[before:] if c == "extraction"]
        self.assertEqual(late, ["extraction"])

    # ---- §3 prompt diet -------------------------------------------------
    def test_diet_scales_slice_per_mode(self):
        ret = KnowledgeRetriever(root=self._kroot(), brain_store=self.brain)
        brain_profile = {"id": "restaurant", "goals": ["grow"],
                         "typical_sections": ["home"], "features": ["x"],
                         "conversion": {"cta": "call"},
                         "objections": ["price"]}
        full = ret.retrieve("restaurant", brain_profile=dict(brain_profile))
        need = ret.retrieve("restaurant", brain_profile=dict(brain_profile),
                            mode="NEED")
        shaping = ret.retrieve("restaurant", brain_profile=dict(brain_profile),
                               mode="SHAPING")
        commercial = ret.retrieve("restaurant",
                                  brain_profile=dict(brain_profile),
                                  mode="COMMERCIAL")

        def size(m):
            return len(str(m.get("extension"))) + \
                len(str(m.get("brain_profile")))

        self.assertLess(size(need), size(full))
        self.assertLess(size(commercial), size(shaping))
        self.assertEqual(list(need["extension"]), ["common_pain_points"])
        self.assertEqual(shaping["extension"], {})
        self.assertEqual(commercial["extension"], {})
        self.assertEqual(sorted(commercial["brain_profile"]), ["id"])
        self.assertNotIn("conversion", need["brain_profile"])

    # ---- §4 typing indicator --------------------------------------------
    def test_telegram_typing_fires_on_receipt(self):
        provider = self.tg_adapter.provider  # MockTelegramProvider
        body = {"update_id": int(uuid.uuid4().int % 1e9), "message": {
            "message_id": 77, "date": 0,
            "chat": {"id": 555001}, "from": {"id": 555001},
            "text": "مرحبا"}}
        self.coord.handle_inbound("telegram", body)
        actions = getattr(provider, "chat_actions", [])
        self.assertTrue(actions, "typing action must fire at receipt")
        self.assertEqual(actions[0]["action"], "typing")

    # ---- §5 first-pass metrics -------------------------------------------
    def test_first_pass_row_recorded(self):
        metrics = Path(self.tmp) / "storage" / "metrics"
        self.coord._METRICS_DIR = metrics
        self.coord._log_draft_outcome("corr-x", "NEED", "first_pass", "", 42)
        rows = [ln for ln in
                (metrics / "first_pass.jsonl").read_text().splitlines() if ln]
        row = json.loads(rows[-1])
        self.assertEqual(row["outcome"], "first_pass")
        self.assertEqual(row["mode"], "NEED")
        self.assertEqual(row["chars"], 42)

    # ---- §6 validator -----------------------------------------------------
    def test_service_details_pack_validates_without_filler(self):
        pack_path = ROOT / "knowledge" / "packs" / "service_details.v1.yaml"
        raw = pack_path.read_text()
        self.assertNotIn("common_processes: []", raw,
                         "filler padding must be gone")
        p = Path(self.tmp) / "service_details.v1.yaml"
        p.write_text(raw)
        self.assertEqual(validate_industry_pack(p), [])

    def test_bad_statement_kind_still_fails_meta_pack(self):
        raw = (ROOT / "knowledge" / "packs" /
               "service_details.v1.yaml").read_text().replace(
                   "RECOMMENDATION", "GUARANTEE")
        p = Path(self.tmp) / "svc.yaml"
        p.write_text(raw)
        errs = validate_industry_pack(p)
        self.assertTrue(any("RECOMMENDATION" in e for e in errs))

    def test_industry_pack_missing_fields_still_fails(self):
        import yaml
        broken = yaml.safe_dump({"id": "restaurant",
                                 "brain_profile_id": "restaurant"})
        p = Path(self.tmp) / "broken.yaml"
        p.write_text(broken)
        errs = validate_industry_pack(p)
        self.assertTrue(any("missing field" in e for e in errs))

    # ---- helpers ---------------------------------------------------------
    def _kroot(self):
        return ROOT / "knowledge"

    def _body(self, text):
        return {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "905345247791"},
                    "contacts": [{"wa_id": WA}],
                    "messages": [{"from": WA,
                                  "id": f"p12_{uuid.uuid4().hex[:10]}",
                                  "type": "text",
                                  "text": {"body": text}}]}}]}]}


if __name__ == "__main__":
    unittest.main()
