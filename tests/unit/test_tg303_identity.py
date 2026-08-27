"""TG-303 — Telegram identity lifecycle on platform_identities (Phase 5/24).

Exact-match resolution, no duplicates, and NO automatic merge with WhatsApp
identities (owner action only). Owner slash-commands sent by a CUSTOMER are
plain business text — never executed.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from tests._db import fresh_db, wipe  # noqa: E402

from amancore.channels.canonical import InboundMessage  # noqa: E402
from amancore.channels.coordinator import MessageCoordinator  # noqa: E402
from amancore.crm.service import CRMService  # noqa: E402


def _coord(db):
    coord = MessageCoordinator.__new__(MessageCoordinator)
    coord.crm = CRMService(db)
    coord.outbox = MagicMock(); coord.worker = MagicMock()
    coord.worker.drain.return_value = []
    wa = MagicMock()
    wa.config.get.return_value = False
    wa.receive_webhook.return_value = []
    wa.channel = "whatsapp"
    coord.adapters = {"whatsapp": wa}
    coord.whatsapp = wa
    coord.handover = MagicMock(); coord.handover.can_send_ai.return_value = False
    coord.channel_policy = MagicMock()
    coord.channel_policy.evaluate_send.return_value = "allow"
    coord.idem = MagicMock(); coord.idem.check.return_value = None
    coord.idem.store = lambda *a, **k: None
    coord.message_recorder = None; coord.status_recorder = None
    coord.reaction_recorder = None; coord.dispatcher = None
    coord.owner_alert = lambda *a, **k: None
    coord.audit = MagicMock()
    coord.lang = MagicMock(); coord.lang.detect.return_value = "ar"
    coord.memory = MagicMock()
    coord.memory.get_or_create.return_value = {"conversation_id": "c"}
    coord.cost_governor = None
    return coord


def _tg(ext_id, text, mid="m1"):
    return InboundMessage(channel="telegram", external_message_id=mid,
                          external_user_id=ext_id, text=text, name="TG User")


class IdentityLifecycle(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db(); wipe(self.db)
        self.coord = _coord(self.db)

    def tearDown(self):
        pass

    def _identity_lead(self, channel, ext):
        row = self.db.execute(
            "SELECT l.lead_id FROM platform_identities i"
            " JOIN leads l ON l.lead_id=i.lead_id"
            " WHERE i.channel=? AND i.external_user_id=?",
            (channel, ext)).fetchone()
        return row["lead_id"] if row else None

    def test_first_telegram_user_creates_identity_and_lead(self):
        self.coord._process_inbound(_tg("777000", "مرحبا", mid="t1"))
        lead = self._identity_lead("telegram", "777000")
        self.assertIsNotNone(lead)

    def test_repeated_user_resolves_same_lead_no_duplicate(self):
        for i in range(3):
            self.coord._process_inbound(_tg("777000", f"msg {i}", mid=f"t{i}"))
        lead = self._identity_lead("telegram", "777000")
        n_leads = self.db.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        n_ident = self.db.execute(
            "SELECT COUNT(*) c FROM platform_identities WHERE channel='telegram'"
        ).fetchone()["c"]
        self.assertEqual(n_leads, 1)
        self.assertEqual(n_ident, 1)
        self.assertIsNotNone(lead)

    def test_no_auto_merge_with_whatsapp_identity(self):
        # same HUMAN, two platforms, distinct provider ids → two identities,
        # two leads; merging is an explicit OWNER action (design D4)
        from amancore.channels.canonical import InboundMessage as IM

        self.coord._process_inbound(IM(channel="whatsapp",
                                       external_message_id="w1",
                                       external_user_id="905551112233",
                                       text="hi", name="WA User"))
        self.coord._process_inbound(_tg("777000", "hi", mid="t1"))
        wa_lead = self._identity_lead("whatsapp", "905551112233")
        tg_lead = self._identity_lead("telegram", "777000")
        self.assertIsNotNone(wa_lead)
        self.assertIsNotNone(tg_lead)
        self.assertNotEqual(wa_lead, tg_lead)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) c FROM leads").fetchone()["c"], 2)

    def test_customer_slash_commands_are_plain_text_not_owner_actions(self):
        before = self.db.execute(
            "SELECT COUNT(*) c FROM approvals").fetchone()["c"]
        for i, cmd in enumerate(("/approve 100", "/status", "/leads",
                                 "/mode production", "/send hi to all")):
            res = self.coord._process_inbound(_tg("777000", cmd, mid=f"c{i}"))
            self.assertTrue(res.get("lead_id"), cmd)   # handled as BUSINESS text
        after = self.db.execute(
            "SELECT COUNT(*) c FROM approvals").fetchone()["c"]
        self.assertEqual(before, after, "customer executed an owner command!")


if __name__ == "__main__":
    unittest.main()
