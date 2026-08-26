"""THE SEVENTH-CHANNEL TEST — the architectural proof (task Phase 22).

A fake channel adapter ("signal") is plugged into the REAL core:
webhook → coordinator → CRM identity → sales → compliance → outbox →
ChannelRouter → fake adapter.send → audit. NOTHING under sales/, support/,
pricing/, crm/, compliance/, services/ is modified or monkey-patched to make
this pass. If future code introduces channel-specific imports into the Core,
tests/architecture/test_channel_boundaries.py fails.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from amancore.channels.canonical import ChannelCapabilities  # noqa: E402
from amancore.channels.contract import ChannelAdapter  # noqa: E402
from amancore.services.events import CanonicalEvent  # noqa: E402
from tests.common import make_db  # noqa: E402


class SignalAdapter(ChannelAdapter):
    """Fake SEVENTH channel — proves the core accepts plug-in channels."""

    channel = "signal"

    def __init__(self):
        self.config = {"signature_required": False}
        self.sent: list[dict] = []
        self.inbox: list[dict] = []

    def capabilities(self):
        return ChannelCapabilities(text=True, reply_context=True)

    def normalize_recipient(self, raw) -> str:
        return f"sig-{raw}"          # provider addressing dialect

    def verify_webhook(self, mode, token, challenge):
        if token == "sig-token":
            return {"verified": True, "challenge": challenge}
        return {"verified": False}

    def receive_webhook(self, body, headers=None):
        events = []
        for msg in (body or {}).get("messages", []):
            self.inbox.append(msg)
            events.append(CanonicalEvent(
                event_id=f"ev-{msg['id']}",
                event_type="message.received",
                timestamp="2026-08-26T00:00:00+00:00",
                source="signal", channel="signal", actor_type="external",
                actor_id=msg["from"],
                idempotency_key=f"sg:{msg['id']}", risk_level="low",
                payload={"external_user_id": msg["from"], "name": msg.get("name", ""),
                         "message_type": "text", "text": msg["text"]},
                metadata={"provider_message_id": msg["id"]}))
        return events

    def send(self, recipient, message_type, payload):
        self.sent.append({"to": recipient, "type": message_type,
                          "payload": payload})
        return {"provider_message_id": f"sgm-{len(self.sent)}", "status": "sent"}

    def classify_error(self, exc):
        return None, None


class SeventhChannelTest(unittest.TestCase):
    def setUp(self):
        import os

        # never touch production DB — restored in tearDown
        self._old_iso = os.environ.pop("AMANCORE_ISOLATED", None)
        os.environ["AMANCORE_ISOLATED"] = "1"
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self.tmp.name) / "t.db")
        from amancore.agents.sales import SalesAgent
        from amancore.business_brain.store import BrainStore
        from amancore.channels.coordinator import MessageCoordinator
        from amancore.channels.handover import HandoverService
        from amancore.channels.language import LanguageDetector
        from amancore.channels.outbox import MessageOutbox, OutboxWorker
        from amancore.channels.policy import ChannelPolicyEngine
        from amancore.channels.response_filter import ExternalResponseFilter
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
        audit = AuditService(self.db)
        dispatcher = EventDispatcher()
        crm = CRMService(self.db)
        memory = ConversationMemory(crm)
        sales = SalesAgent(brain, crm, memory, DiscoveryEngine(),
                           QualificationEngine(), ObjectionHandlingSkill(brain),
                           FollowupEngine(), HandoffService(dispatcher),
                           audit=audit, dispatcher=dispatcher)
        policy = ChannelPolicyEngine(brain)
        outbox = MessageOutbox(self.db)
        worker = OutboxWorker(outbox, {}, policy, audit=audit)  # adapters wired below
        self.signal = SignalAdapter()
        self.coordinator = MessageCoordinator(
            {"whatsapp": SignalAdapter(), "signal": self.signal},
            outbox, worker, sales, crm, memory,
            HandoverService(crm), ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **k: None,
            audit=audit, dispatcher=dispatcher)
        # rebind worker's router so 'signal' resolves through the SAME registry
        worker.router.register(self.signal)
        # canonical transcript recorder (mirrors build_runtime composition)
        def _record(direction, channel, external_user_id, lead_id,
                    external_message_id=None, body="",
                    quoted_external_message_id=None, **_):
            self.db.execute(
                "INSERT INTO channel_messages (direction, channel, external_user_id,"
                " lead_id, external_message_id, body, status, created_at,"
                " quoted_external_message_id)"
                " VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)",
                (direction, channel, external_user_id, lead_id,
                 external_message_id, body, "2026-08-26T00:00:00+00:00",
                 quoted_external_message_id))
            self.db.commit()
        self.coordinator.message_recorder = _record

    def tearDown(self):
        import os

        self.db.close()
        self.tmp.cleanup()
        if self._old_iso is None:
            os.environ.pop("AMANCORE_ISOLATED", None)
        else:
            os.environ["AMANCORE_ISOLATED"] = self._old_iso

    def test_seventh_channel_end_to_end(self):
        body = {"messages": [{"id": "s-1", "from": "user-777", "name": "Seventh",
                              "text": "hello, I need a website"}]}
        summary = self.coordinator.handle_inbound("signal", body)
        self.assertEqual(summary["received"], 1)
        self.assertEqual(summary["processed"], 1)
        self.assertGreaterEqual(summary["replies"], 1)

        # 1) identity created for the NEW channel
        row = self.db.execute(
            "SELECT l.lead_id FROM platform_identities i"
            " JOIN leads l ON l.lead_id = i.lead_id"
            " WHERE i.channel='signal' AND i.external_user_id='user-777'").fetchone()
        self.assertIsNotNone(row, "no lead identity for seventh channel")
        lead_id = row["lead_id"]

        # 2) transcript recorded with canonical columns + channel
        m = self.db.execute(
            "SELECT channel, external_user_id FROM channel_messages"
            " WHERE lead_id=? AND direction='in'", (lead_id,)).fetchone()
        self.assertEqual(m["channel"], "signal")
        self.assertEqual(m["external_user_id"], "user-777")

        # 3) reply routed THROUGH THE ROUTER to the fake adapter — proving the
        #    outbox never hard-codes any provider
        self.assertTrue(self.signal.sent, "adapter.send was never called")
        sent = self.signal.sent[0]
        self.assertTrue(str(sent["to"]).startswith("sig-user-777"))
        self.assertEqual(sent["type"], "text")

        # 4) outbox row is channel-tagged and marked sent via router path
        ob = self.db.execute(
            "SELECT channel, status FROM message_outbox WHERE lead_id=?"
            " ORDER BY created_at DESC LIMIT 1", (lead_id,)).fetchone()
        self.assertEqual(ob["channel"], "signal")

        # 5) audit trail exists for the send
        a = self.db.execute(
            "SELECT COUNT(*) c FROM audit_events WHERE action='channel.sent'"
            " AND resource='signal'").fetchone()["c"]
        self.assertGreaterEqual(a, 1)

        # 6) webhook verification works through the same generic entry
        ok = self.coordinator._adapter_for("signal").verify_webhook(
            "subscribe", "sig-token", "ch-42")
        self.assertEqual(ok["challenge"], "ch-42")


if __name__ == "__main__":
    unittest.main()
