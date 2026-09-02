"""Integration test for MessageCoordinator with Requirements Intelligence Layer (RIL)."""

import unittest
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

from amancore.storage.db import open_database
from amancore.crm.service import CRMService
from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.canonical import InboundMessage
from amancore.sales.conversation_memory import ConversationMemory
from amancore.requirements.service import RequirementsService


class TestRequirementsCoordinatorFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_aman.db"
        schema_path = Path(__file__).resolve().parents[2] / "amancore" / "storage" / "schema.sql"
        self.db = open_database(db_path, schema_path)
        self.crm = CRMService(self.db)
        self.memory = ConversationMemory(self.crm)
        self.ril = RequirementsService(self.crm)

        # Mock adapter & agents for coordinator
        self.adapter = MagicMock()
        self.adapter.channel = "whatsapp"
        self.sales_agent = MagicMock()
        self.sales_agent.process_message.return_value = {
            "reply": "مرحباً بك! سأساعدك في بناء موقعك.",
            "next_action": "ask_next_question",
            "qualification": {"missing_information": ["budget", "timeline"]},
        }
        self.handover = MagicMock()
        self.handover.can_send_ai.return_value = True

        self.coordinator = MessageCoordinator(
            adapters={"whatsapp": self.adapter},
            outbox=MagicMock(),
            worker=MagicMock(),
            sales_agent=self.sales_agent,
            crm=self.crm,
            conversation_memory=self.memory,
            handover=self.handover,
            response_filter=MagicMock(check=lambda t: {"allowed": True, "reasons": []}),
            channel_policy=MagicMock(),
            idempotency=MagicMock(check=lambda *a: True, record=lambda *a: None),
            language_detector=MagicMock(detect=lambda t: "ar"),
            localization_skill=MagicMock(localize=lambda t, r, l: {"text": t}),
            snapshot_store=MagicMock(),
            proposal_store=MagicMock(),
            owner_alert=MagicMock(),
            requirements_service=self.ril,
        )

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_inbound_message_triggers_ril_and_persists_requirements(self):
        msg = InboundMessage(
            channel="whatsapp",
            external_user_id="62811223344",
            external_message_id="msg_wa_99",
            text="أريد متجر إلكتروني لبيع العطور مع ربط بوابة الدفع Stripe وباللغتين عربي وإنجليزي",
        )

        res = self.coordinator._process_inbound(msg)
        self.assertTrue(res.get("reply_sent"))
        lead_id = res["lead_id"]

        # Check that requirements were cleanly extracted and stored in SQLite database
        reqs = self.crm.list_requirements_for_lead(lead_id)
        self.assertTrue(len(reqs) >= 2)
        
        # Verify subcategories
        subcats = {r["subcategory"] for r in reqs}
        self.assertIn("ecommerce", subcats)
        self.assertIn("payments", subcats)

        # Verify source traceability
        for r in reqs:
            self.assertEqual(r["source_message_id"], "msg_wa_99")
            self.assertEqual(r["lead_id"], lead_id)
            self.assertIn(r["certainty"], ["explicit", "inferred"])

        # Verify decisions stored
        decs = self.crm.list_decisions_for_lead(lead_id)
        self.assertTrue(len(decs) >= 1)
        lang_dec = next((d for d in decs if d["topic"] == "languages"), None)
        self.assertIsNotNone(lang_dec)
        self.assertIn("Arabic + English", lang_dec["decision"])


if __name__ == "__main__":
    unittest.main()
