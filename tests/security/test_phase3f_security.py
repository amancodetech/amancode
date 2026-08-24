import json
import unittest

from amancore.analytics.service import AnalyticsService
from amancore.agents.support import SupportAgent
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.crm.service import CRMService
from amancore.errors import ProductionNotEnabledError
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_db


class Phase3FSecurityTest(TempDirTestCase, unittest.TestCase):
    """Boundaries that must never be crossed (spec section 37)."""

    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_production_cannot_activate_accidentally(self):
        # mode=production + production_enabled=false -> blocked even with credentials
        adapter = WhatsAppAdapter({
            "mode": "production", "production_enabled": False,
            "phone_number_id": "111", "api_version": "v24.0",
            "base_url": "https://graph.facebook.com",
        })
        adapter.provider.access_token = "EA-fake-token"
        with self.assertRaises(ProductionNotEnabledError):
            adapter.send("5511", "text", "hello")
        # sandbox is also blocked unless explicitly enabled
        adapter2 = WhatsAppAdapter({
            "mode": "sandbox", "production_enabled": False, "phone_number_id": "111",
        })
        with self.assertRaises(ProductionNotEnabledError):
            adapter2.send("5511", "text", "hello")

    def test_no_secrets_in_analytics_reports(self):
        import os

        os.environ["WHATSAPP_ACCESS_TOKEN"] = "SENSITIVE_TOKEN_ABC123"
        try:
            crm = CRMService(self.db)
            crm.create_lead(source_channel="whatsapp", company="X")
            svc = AnalyticsService(self.db)
            report = json.dumps(svc.report_daily("2999-01-01"))
            report += json.dumps(svc.kpi_catalog())
            self.assertNotIn("SENSITIVE_TOKEN_ABC123", report)
            self.assertNotIn("WHATSAPP_ACCESS_TOKEN", report)
        finally:
            os.environ.pop("WHATSAPP_ACCESS_TOKEN", None)

    def test_support_cannot_issue_refund_or_change_pricing(self):
        from tests.common import make_brain

        agent = SupportAgent(
            make_brain(self.tmp), CRMService(self.db), SupportCaseStore(self.db),
            handover=None, owner_alert=lambda *a, **kw: None, support_policy={},
        )
        for banned in ("refund", "apply_discount", "change_price", "change_scope",
                       "change_contract", "extend_deadline", "approve_price",
                       "write_business_brain", "send_external"):
            self.assertFalse(hasattr(agent, banned), f"SupportAgent must not expose {banned}")

    def test_analytics_cannot_mutate_crm(self):
        crm = CRMService(self.db)
        crm.create_lead(source_channel="whatsapp")
        svc = AnalyticsService(self.db)
        for banned in ("create_lead", "update_lead", "create_opportunity", "won_opportunity",
                       "create_customer", "create_project", "create_care_plan",
                       "send", "enqueue", "publish_content", "write_business_brain"):
            self.assertFalse(hasattr(svc, banned), f"AnalyticsService must not expose {banned}")

    def test_analytics_cannot_send_messages(self):
        svc = AnalyticsService(self.db)
        self.assertFalse(hasattr(svc, "send"))
        self.assertFalse(hasattr(svc, "outbox"))
        self.assertFalse(hasattr(svc, "worker"))
        # and computing KPIs must not touch outbox
        from amancore.channels.outbox import MessageOutbox

        outbox = MessageOutbox(self.db)
        svc.funnel()
        self.assertEqual(outbox.counts().get("queued", 0), 0)

    def test_support_case_store_has_no_pricing_authority(self):
        store = SupportCaseStore(self.db)
        self.assertFalse(hasattr(store, "approve_price"))
        self.assertFalse(hasattr(store, "apply_discount"))


if __name__ == "__main__":
    unittest.main()
