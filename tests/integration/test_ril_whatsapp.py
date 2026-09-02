"""Integration Tests for WhatsApp Channel Adapter & RIL Ingestion."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    ChannelProjectResolver,
    RILIntegrationService,
    WhatsAppAdapter,
)
from tests.fixtures import isolated_db, ids, clock


class TestRILWhatsAppIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_whatsapp_cloud_api_webhook_flow_and_response(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = WhatsAppAdapter(resolver, ril_service)

            raw_payload = {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "10001",
                        "changes": [
                            {
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {"display_phone_number": "905551112233", "phone_number_id": "phone_01"},
                                    "contacts": [{"profile": {"name": "Ahmed Ali"}, "wa_id": "905551112233"}],
                                    "messages": [
                                        {
                                            "from": "905551112233",
                                            "id": "wamid.HBgL...",
                                            "timestamp": "1725280000",
                                            "text": {"body": "أريد متجر إلكتروني وبوابة دفع وعملة SAR"},
                                            "type": "text",
                                        }
                                    ],
                                },
                                "field": "messages",
                            }
                        ],
                    }
                ],
            }

            resp = adapter.handle_inbound(raw_payload)
            self.assertEqual(resp["channel"], "whatsapp")
            self.assertIn("text", resp)
            self.assertGreaterEqual(resp["ril_summary"]["requirements_count"], 2)

            # Assert Lead created and requirements persisted
            lead = crm.find_lead_by_whatsapp("905551112233")
            self.assertIsNotNone(lead)
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertGreaterEqual(len(reqs), 2)

    def test_whatsapp_bridge_format_and_idempotent_replay(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = WhatsAppAdapter(resolver, ril_service)

            bridge_payload = {
                "from": "628123456789",
                "name": "Budi Santoso",
                "id": "wa_bridge_mid_001",
                "body": "أريد نظام حجوزات أونلاين وعملة IDR",
            }

            # First delivery
            resp1 = adapter.handle_inbound(bridge_payload)
            self.assertEqual(resp1["channel"], "whatsapp")
            count1 = resp1["ril_summary"]["requirements_count"]

            # Duplicate delivery
            resp2 = adapter.handle_inbound(bridge_payload)
            self.assertEqual(resp2["channel"], "whatsapp")
            self.assertEqual(resp2["ril_summary"]["requirements_count"], count1)

            # Assert database has no duplicate requirements
            lead = crm.find_lead_by_whatsapp("628123456789")
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertEqual(len(reqs), count1)


if __name__ == "__main__":
    unittest.main()
