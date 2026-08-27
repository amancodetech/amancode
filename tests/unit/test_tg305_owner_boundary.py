"""TG-305 — Owner console ≠ customer channel (Phases 18/19/28).

The owner whitelist (TELEGRAM_CHAT_ID) is authoritative for OWNER commands;
customer Telegram messages flow through the business coordinator and can
NEVER execute /approve /status /leads /mode /send.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from tests._db import fresh_db, wipe  # noqa: E402

from amancore.ops.telegram_console import (  # noqa: E402
    HELP_TEXT, TelegramOwnerConsole,
)


class OwnerConsoleWhitelist(unittest.TestCase):
    def setUp(self):
        self.console = TelegramOwnerConsole({})
        self.console.token = "OWNER-BOT-TOKEN"
        self.console.chat_id = "111"
        self.dispatched, self.replied = [], []

    def test_unauthorized_chat_cannot_execute_owner_commands(self):
        self.console._dispatch = lambda cmd, args: (self.dispatched.append(cmd),
                                                    "EXECUTED")[1]
        self.console._reply = lambda text: self.replied.append(text)
        for cmd in ("/approve 100", "/status", "/leads", "/mode production",
                    "/send spam", "hello?"):
            self.console._handle_update(
                {"message": {"chat": {"id": 999}, "text": cmd}})
        self.assertEqual(self.dispatched, [], "stranger executed owner command")
        self.assertEqual(self.replied, [], "console answered a stranger")

    def test_authorized_owner_chat_reaches_dispatcher(self):
        self.console._dispatch = lambda cmd, args: (self.dispatched.append(cmd),
                                                    HELP_TEXT)[1]
        self.console._reply = lambda text: self.replied.append(text)
        self.console._handle_update(
            {"message": {"chat": {"id": 111}, "text": "/help"}})
        self.assertEqual(self.dispatched, ["help"])
        self.assertEqual(self.replied, [HELP_TEXT])

    def test_console_and_customer_use_distinct_bot_tokens(self):
        """Customer adapter env var must differ from the owner console's."""
        from amancore.channels.telegram import TelegramAdapter

        self.assertNotEqual(
            TelegramAdapter({}).config.get("bot_token_env",
                                           "TELEGRAM_CUSTOMER_BOT_TOKEN"),
            "TELEGRAM_BOT_TOKEN")


class CustomerCannotTriggerConsole(unittest.TestCase):
    """A message that LOOKS like an owner command arriving on the CUSTOMER
    channel is processed as business text — approvals table untouched."""

    def setUp(self):
        self.db = fresh_db(); wipe(self.db)

    def _coord_like_tg303(self):
        from amancore.channels.coordinator import MessageCoordinator
        from amancore.crm.service import CRMService

        coord = MessageCoordinator.__new__(MessageCoordinator)
        coord.crm = CRMService(self.db)
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

    def test_approve_via_customer_channel_creates_no_approval(self):
        from amancore.channels.canonical import InboundMessage

        coord = self._coord_like_tg303()
        before = self.db.execute(
            "SELECT COUNT(*) c FROM approvals").fetchone()["c"]
        for i, cmd in enumerate(("/approve 500", "/approve 999999")):
            res = coord._process_inbound(InboundMessage(
                channel="telegram", external_message_id=f"x{i}",
                external_user_id="777000", text=cmd))
            self.assertTrue(res.get("lead_id"))
        after = self.db.execute(
            "SELECT COUNT(*) c FROM approvals").fetchone()["c"]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
