"""TG-306 — REALISTIC END-TO-END (Phase 25).

SCENARIO A: Telegram user "أريد موقع شركة، كم السعر؟" → webhook → adapter →
canonical → identity → lead → intent/pricing → AI draft (ModelRouter seam) →
compliance/governor seams → outbox → ChannelRouter → adapter → provider mock
→ audit.

SCENARIO B: WhatsApp user sends the SAME text through the SAME core.

SCENARIO C: same human with WA + TG identities — distinct identities/leads,
no automatic merge, per-channel transcripts.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from tests._db import fresh_db, wipe  # noqa: E402

TG_SECRET = "e2e-tg-secret"


def _tg_update(text, update_id=7001, message_id=601, user_id=777000):
    return {"update_id": update_id, "message": {
        "message_id": message_id,
        "from": {"id": user_id, "is_bot": False, "first_name": "Sami"},
        "chat": {"id": user_id, "type": "private"},
        "date": 1777777777,
        "text": text,
    }}


def _wa_body(text, wa_id="905551112233", msg_id="wamid.e2e1"):
    return {"object": "whatsapp_business_account", "entry": [
        {"changes": [{"value": {
            "contacts": [{"wa_id": wa_id, "profile": {"name": "WA User"}}],
            "messages": [{"from": wa_id, "id": msg_id, "type": "text",
                          "text": {"body": text}}],
        }}]}]}


class FakeResult:
    text = "ردّ تجريبي من مساعد AmanCode"


class FakeDrafter:
    def complete(self, messages, **kw):
        return FakeResult()


class DualChannelE2E(unittest.TestCase):
    def setUp(self):
        self._old_secret = os.environ.pop("TELEGRAM_CUSTOMER_WEBHOOK_SECRET", None)
        os.environ["TELEGRAM_CUSTOMER_WEBHOOK_SECRET"] = TG_SECRET
        self.db = fresh_db(); wipe(self.db)
        self._build()

    def tearDown(self):
        if self._old_secret is None:
            os.environ.pop("TELEGRAM_CUSTOMER_WEBHOOK_SECRET", None)
        else:
            os.environ["TELEGRAM_CUSTOMER_WEBHOOK_SECRET"] = self._old_secret

    def _build(self):
        from amancore.agents.sales import SalesAgent
        from amancore.business_brain.store import BrainStore
        from amancore.channels.coordinator import MessageCoordinator
        from amancore.channels.handover import HandoverService
        from amancore.channels.language import LanguageDetector
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from amancore.channels.response_filter import ExternalResponseFilter
        from amancore.channels.router import ChannelRouter
        from amancore.channels.telegram import MockTelegramProvider, TelegramAdapter
        from amancore.channels.whatsapp import (
            MockWhatsAppProvider, WhatsAppAdapter,
        )
        from amancore.crm.service import CRMService
        from amancore.pricing.proposal import ProposalStore
        from amancore.pricing.snapshot import PricingSnapshotStore
        from amancore.sales.conversation_memory import ConversationMemory
        from amancore.sales.discovery import DiscoveryEngine
        from amancore.sales.followup import FollowupEngine
        from amancore.sales.handoff import HandoffService
        from amancore.sales.qualification import QualificationEngine
        from amancore.services.audit import AuditService
        from amancore.services.events import EventDispatcher, IdempotencyStore
        from amancore.skills.localization import LocalizationSkill
        from amancore.skills.objection_handling import ObjectionHandlingSkill

        brain = BrainStore(ROOT / "amancore" / "business_brain")
        self.audit = AuditService(self.db)
        dispatcher = EventDispatcher()
        crm = CRMService(self.db)
        memory = ConversationMemory(crm)
        sales = SalesAgent(brain, crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(brain),
                           FollowupEngine(), HandoffService(dispatcher),
                           audit=self.audit, dispatcher=dispatcher)

        tg_cfg = {"mode": "mock", "signature_required": True,
                  "enabled": True, "customer_messaging": True}
        wa_cfg = {"mode": "mock", "signature_required": False}
        self.tg_provider = MockTelegramProvider()
        self.wa_provider = MockWhatsAppProvider()
        tg_adapter = TelegramAdapter(tg_cfg, provider=self.tg_provider)
        wa_adapter = WhatsAppAdapter(wa_cfg, provider=self.wa_provider)
        router = ChannelRouter({"whatsapp": wa_adapter, "telegram": tg_adapter})
        policy = ChannelPolicyEngine(brain, {"whatsapp": {}, "telegram": {
            "enabled": True, "customer_messaging": True}})
        outbox = MessageOutbox(self.db)
        worker = OutboxWorker(outbox, router, policy, audit=self.audit)

        self.coord = MessageCoordinator(
            {"whatsapp": wa_adapter, "telegram": tg_adapter},
            outbox, worker, sales, crm, memory,
            HandoverService(crm), ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=self.audit, dispatcher=dispatcher)
        # deterministic AI drafting through the ModelRouter SEAM (Phase 16:
        # production path is coord._drafter = ModelRouter(task=ROUTINE))
        self.coord._drafter = FakeDrafter()

        def _record(direction, channel, external_user_id, lead_id,
                    external_message_id=None, body="",
                    quoted_external_message_id=None, **_):
            from amancore.ids import utcnow

            self.db.execute(
                "INSERT INTO channel_messages (direction, channel,"
                " external_user_id, lead_id, external_message_id, body, status,"
                " created_at, quoted_external_message_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (direction, channel, external_user_id, lead_id,
                 external_message_id, body, "", utcnow(),
                 quoted_external_message_id))
            self.db.commit()
        self.coord.message_recorder = _record
        self.outbox = outbox

    # ---- helpers --------------------------------------------------------
    def _sync_out_rows(self):
        """Production composes this sync into the runtime; mirror it here so
        outbound transcript rows exist exactly as they do live."""
        from amancore.channels.webhook_server import sync_channel_messages

        sync_channel_messages(self.db)

    def _identity_lead(self, channel, ext):
        row = self.db.execute(
            "SELECT l.lead_id FROM platform_identities i"
            " JOIN leads l ON l.lead_id=i.lead_id"
            " WHERE i.channel=? AND i.external_user_id=?",
            (channel, ext)).fetchone()
        return row["lead_id"] if row else None

    def _audit_count(self, action, resource):
        return self.db.execute(
            "SELECT COUNT(*) c FROM audit_events WHERE action=? AND resource=?",
            (action, resource)).fetchone()["c"]

    # ---- SCENARIO A -----------------------------------------------------
    def test_scenario_a_telegram_pricing_flow_end_to_end(self):
        summary = self.coord.handle_inbound(
            "telegram", _tg_update("أريد موقع شركة، كم السعر؟"),
            headers={"x-telegram-bot-api-secret-token": TG_SECRET})
        self._sync_out_rows()
        self.assertEqual(summary["received"], 1)
        self.assertEqual(summary["processed"], 1)
        self.assertGreaterEqual(summary["replies"], 1)

        lead = self._identity_lead("telegram", "777000")
        self.assertIsNotNone(lead, "no telegram identity/lead created")

        # reply went OUT through the router to the telegram provider only
        self.assertEqual(len(self.tg_provider.sent), 1)
        self.assertEqual(self.tg_provider.sent[0]["recipient"], "777000")
        self.assertEqual(len(self.wa_provider.sent), 0)

        row = self.outbox.db.execute(
            "SELECT channel, status FROM message_outbox WHERE lead_id=?"
            " ORDER BY created_at DESC LIMIT 1", (lead,)).fetchone()
        self.assertEqual(row["channel"], "telegram")
        self.assertEqual(row["status"], "sent")

        # canonical transcript both directions
        dirs = {r["direction"]: r["channel"] for r in self.db.execute(
            "SELECT direction, channel FROM channel_messages WHERE lead_id=?",
            (lead,))}
        self.assertEqual(dirs.get("in"), "telegram")
        self.assertEqual(dirs.get("out"), "telegram")

        self.assertGreaterEqual(self._audit_count("channel.sent", "telegram"), 1)

    def test_unsigned_telegram_post_rejected(self):
        summary = self.coord.handle_inbound(
            "telegram", _tg_update("hello"), headers={})
        self.assertEqual(summary.get("status"), "rejected")
        self.assertEqual(summary.get("reason"), "invalid signature")
        self.assertEqual(len(self.tg_provider.sent), 0)

    # ---- SCENARIO B -----------------------------------------------------
    def test_scenario_b_whatsapp_same_core_same_behavior(self):
        summary = self.coord.handle_inbound("whatsapp", _wa_body(
            "أريد موقع شركة، كم السعر؟"))
        self._sync_out_rows()
        self.assertEqual(summary["processed"], 1)
        self.assertGreaterEqual(summary["replies"], 1)
        lead = self._identity_lead("whatsapp", "905551112233")
        self.assertIsNotNone(lead)
        self.assertEqual(len(self.wa_provider.sent), 1)
        self.assertEqual(len(self.tg_provider.sent), 0)
        row = self.outbox.db.execute(
            "SELECT channel, status FROM message_outbox WHERE lead_id=?"
            " ORDER BY created_at DESC LIMIT 1", (lead,)).fetchone()
        self.assertEqual(row["channel"], "whatsapp")
        self.assertEqual(row["status"], "sent")

    # ---- SCENARIO C -----------------------------------------------------
    def test_scenario_c_dual_identity_stays_unmerged(self):
        self.coord.handle_inbound("whatsapp", _wa_body("مرحبا", msg_id="wamid.c1"))
        self.coord.handle_inbound(
            "telegram", _tg_update("مرحبا", update_id=7100, message_id=610),
            headers={"x-telegram-bot-api-secret-token": TG_SECRET})
        self._sync_out_rows()
        wa_lead = self._identity_lead("whatsapp", "905551112233")
        tg_lead = self._identity_lead("telegram", "777000")
        self.assertIsNotNone(wa_lead)
        self.assertIsNotNone(tg_lead)
        self.assertNotEqual(wa_lead, tg_lead, "auto-merge happened!")
        n_leads = self.db.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        self.assertEqual(n_leads, 2)
        # transcripts are strictly per-channel/per-lead
        for lead, ch in ((wa_lead, "whatsapp"), (tg_lead, "telegram")):
            rows = self.db.execute(
                "SELECT DISTINCT channel FROM channel_messages"
                " WHERE lead_id=?", (lead,)).fetchall()
            self.assertEqual([r["channel"] for r in rows], [ch])


if __name__ == "__main__":
    unittest.main()
