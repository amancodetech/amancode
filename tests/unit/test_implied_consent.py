"""Plan-B compliance: first inbound message records implied opt-in."""
import sys, unittest
from pathlib import Path
from unittest.mock import MagicMock
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from tests._db import fresh_db, wipe  # noqa: E402
from amancore.crm.service import CRMService  # noqa: E402
from amancore.channels.coordinator import MessageCoordinator  # noqa: E402
from amancore.channels.canonical import InboundMessage  # noqa: E402


class ImpliedConsent(unittest.TestCase):
    def setUp(self):
        self.db = fresh_db(); wipe(self.db)
        coord = MessageCoordinator.__new__(MessageCoordinator)
        coord.crm = CRMService(self.db)
        coord.outbox = MagicMock(); coord.worker = MagicMock()
        coord.worker.drain.return_value = []
        wa = MagicMock()
        wa.config.get.return_value = False
        wa.receive_webhook.return_value = []
        coord.adapters = {"whatsapp": wa}   # canonical adapter registry
        coord.whatsapp = wa
        coord.handover = MagicMock(); coord.handover.can_send_ai.return_value = False
        coord.channel_policy = MagicMock()
        coord.channel_policy.evaluate_send.return_value = "allow"
        coord.idem = MagicMock(); coord.idem.check.return_value = None
        coord.message_recorder = None; coord.status_recorder = None
        coord.reaction_recorder = None; coord.dispatcher = None
        coord.owner_alert = lambda *a, **k: None
        coord.audit = MagicMock()
        coord.lang = MagicMock(); coord.lang.detect.return_value = "ar"
        coord.memory = MagicMock()
        coord.memory.get_or_create.return_value = {"conversation_id": "c"}
        self.coord = coord

    def tearDown(self):
        self.db.close()

    @staticmethod
    def _msg(ext_id, text):
        return InboundMessage(channel="whatsapp", external_message_id=ext_id,
                              external_user_id=ext_id, text=text)

    def test_first_inbound_records_consent_once(self):
        self.coord._process_inbound(self._msg("905555000111", "hi"))
        row = self.db.execute(
            "SELECT l.consent_at AS consent_at, l.consent_source AS consent_source"
            " FROM leads l JOIN platform_identities i ON i.lead_id = l.lead_id"
            " WHERE i.channel='whatsapp' AND i.external_user_id='905555000111'").fetchone()
        self.assertIsNotNone(row["consent_at"])
        self.assertEqual(row["consent_source"], "inbound_first_message")

    def test_repeat_message_no_duplicate_lead(self):
        for mid in ("w1", "w2"):
            self.coord._process_inbound(self._msg("905555000111", "hi"))
        n = self.db.execute("SELECT COUNT(*) c FROM leads").fetchone()[0]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
