"""Integration Tests for Telegram Channel Adapter & RIL Ingestion."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    ChannelProjectResolver,
    RILIntegrationService,
    TelegramAdapter,
)
from tests.fixtures import isolated_db, ids, clock


class TestRILTelegramIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_telegram_update_flow_and_markdown_formatting(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = TelegramAdapter(resolver, ril_service)

            raw_update = {
                "update_id": 9901,
                "message": {
                    "message_id": 7712,
                    "from": {"id": 888123, "first_name": "Tariq", "last_name": "Mansoor", "username": "tariq_m"},
                    "chat": {"id": 888123, "type": "private"},
                    "date": 1725281000,
                    "text": "أريد لوحة تحكم إدارة وربط بوابة دفع مع عملة USD",
                },
            }

            resp = adapter.handle_inbound(raw_update)
            self.assertEqual(resp["channel"], "telegram")
            self.assertEqual(resp["parse_mode"], "Markdown")
            self.assertGreaterEqual(resp["ril_summary"]["requirements_count"], 2)

            # Assert Lead created and identity mapped
            lead = crm.find_lead_by_identity("telegram", "888123")
            self.assertIsNotNone(lead)
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertGreaterEqual(len(reqs), 2)


if __name__ == "__main__":
    unittest.main()
