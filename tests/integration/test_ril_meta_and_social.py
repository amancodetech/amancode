"""Integration Tests for Facebook, Instagram, and TikTok Adapters."""

import unittest
from amancore.crm.service import CRMService
from amancore.requirements.integration import (
    ChannelProjectResolver,
    RILIntegrationService,
)
from amancore.requirements.integration.adapters import MetaAdapter, SocialAdapter
from tests.fixtures import isolated_db, ids, clock


class TestRILMetaAndSocialIntegration(unittest.TestCase):
    def setUp(self):
        ids.reset()
        clock.reset()

    def test_facebook_messenger_inbound_flow(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = MetaAdapter(resolver, ril_service)

            fb_payload = {
                "object": "page",
                "entry": [
                    {
                        "id": "page_001",
                        "messaging": [
                            {
                                "sender": {"id": "fb_user_888"},
                                "message": {"mid": "mid.fb.123", "text": "نحتاج موقع تعريفي مع عملة SAR وبوابة دفع"},
                            }
                        ],
                    }
                ],
            }

            resp = adapter.handle_inbound(fb_payload)
            self.assertIn("message", resp)
            self.assertGreaterEqual(resp["ril_summary"]["requirements_count"], 1)

            # Assert Lead created with Facebook channel
            lead = crm.find_lead_by_identity("facebook", "fb_user_888")
            self.assertIsNotNone(lead)
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertGreaterEqual(len(reqs), 1)

    def test_instagram_dm_inbound_flow(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = MetaAdapter(resolver, ril_service)

            ig_payload = {
                "object": "instagram",
                "entry": [
                    {
                        "id": "ig_page_001",
                        "messaging": [
                            {
                                "sender": {"id": "ig_user_777"},
                                "message": {"mid": "mid.ig.456", "text": "أريد تطبيق جوال لنظام مطاعم"},
                            }
                        ],
                    }
                ],
            }

            resp = adapter.handle_inbound(ig_payload)
            self.assertIn("message", resp)

            lead = crm.find_lead_by_identity("instagram", "ig_user_777")
            self.assertIsNotNone(lead)
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertGreaterEqual(len(reqs), 1)

    def test_tiktok_inbound_flow(self):
        with isolated_db() as db:
            crm = CRMService(db)
            resolver = ChannelProjectResolver(crm)
            ril_service = RILIntegrationService(crm)
            adapter = SocialAdapter(resolver, ril_service)

            tiktok_payload = {
                "channel": "tiktok",
                "tiktok_user_id": "tt_user_999",
                "nickname": "TikTok Creator",
                "comment_id": "tt_cmt_1001",
                "text": "هل يمكن تصميم متجر إلكتروني مع نظام فواتير وعملة USD؟",
            }

            resp = adapter.handle_inbound(tiktok_payload)
            self.assertEqual(resp["status"], "success")
            self.assertIn("reply_text", resp)
            self.assertGreaterEqual(resp["ril_summary"]["requirements_count"], 2)

            lead = crm.find_lead_by_identity("tiktok", "tt_user_999")
            self.assertIsNotNone(lead)
            reqs = crm.list_requirements_for_lead(lead["lead_id"])
            self.assertGreaterEqual(len(reqs), 2)


if __name__ == "__main__":
    unittest.main()
