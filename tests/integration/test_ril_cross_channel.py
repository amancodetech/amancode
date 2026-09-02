"""Integration Tests for Cross-Channel Continuity & Multi-Tenant Separation."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    ChannelProjectResolver,
    RILIntegrationService,
    TelegramAdapter,
    WhatsAppAdapter,
)
from tests.fixtures import isolated_db, ids, clock


class TestRILCrossChannelIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_same_customer_multi_channel_continuity(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            wa_adapter = WhatsAppAdapter(resolver, ril_service)
            tg_adapter = TelegramAdapter(resolver, ril_service)

            # 1. Customer initiates on WhatsApp
            wa_payload = {
                "from": "905001112233",
                "name": "Sami Omar",
                "body": "أريد متجر إلكتروني وتطبيق جوال",
            }
            wa_resp = wa_adapter.handle_inbound(wa_payload)
            lead_id = wa_resp["recipient"]

            # 2. Customer links Telegram account to the same Lead
            crm.add_lead_identity(lead_id=lead_id, channel="telegram", external_user_id="tg_sami_99")

            # 3. Customer continues conversation on Telegram
            tg_update = {
                "message": {
                    "message_id": 101,
                    "from": {"id": "tg_sami_99", "first_name": "Sami"},
                    "text": "العملة المعتمدة هي SAR وبوابة دفع",
                }
            }
            tg_resp = tg_adapter.handle_inbound(tg_update)

            # Assert both channels accumulated into the same unified lead
            reqs = crm.list_requirements_for_lead(lead_id)
            self.assertGreaterEqual(len(reqs), 2)

            decs = crm.list_decisions_for_lead(lead_id, status="active")
            self.assertEqual(len(decs), 1)
            self.assertEqual(decs[0]["decision"], "SAR")

    def test_different_customers_different_channels_strict_isolation(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            wa_adapter = WhatsAppAdapter(resolver, ril_service)
            tg_adapter = TelegramAdapter(resolver, ril_service)

            # Customer A on WhatsApp
            wa_adapter.handle_inbound({
                "from": "905001110001",
                "body": "متجر إلكتروني وعملة USD",
            })
            lead_a = crm.find_lead_by_whatsapp("905001110001")

            # Customer B on Telegram
            tg_adapter.handle_inbound({
                "message": {
                    "message_id": 202,
                    "from": {"id": "tg_cust_b", "first_name": "B"},
                    "text": "نظام حجز مواعيد وعملة IDR",
                }
            })
            lead_b = crm.find_lead_by_identity("telegram", "tg_cust_b")

            self.assertNotEqual(lead_a["lead_id"], lead_b["lead_id"])

            decs_a = crm.list_decisions_for_lead(lead_a["lead_id"], status="active")
            decs_b = crm.list_decisions_for_lead(lead_b["lead_id"], status="active")

            self.assertEqual(decs_a[0]["decision"], "USD")
            self.assertEqual(decs_b[0]["decision"], "IDR")


if __name__ == "__main__":
    unittest.main()
