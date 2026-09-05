"""CH-01 wiring: deferral/mention price wording never enters pricing dispatch."""

import unittest

from tests.common import TempDirTestCase, make_brain, make_db
from tests.integration.test_whatsapp_coordinator import (
    build_coordinator, webhook_body, WA_ID,
)


class PriceDeferralTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        from amancore.crm.service import CRMService
        self.crm = CRMService(self.db)
        self.coord, self.adapter, self.outbox, self.crm, self.audit = \
            build_coordinator(self.db, self.brain, self.crm)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _approvals(self):
        return self.db.execute(
            "SELECT COUNT(*) c FROM approvals WHERE type='final_price'").fetchone()["c"]

    def test_deferral_no_pricing_side_effects(self):
        before = self._approvals()
        self.coord.handle_whatsapp_webhook(
            webhook_body("we can discuss the price later", msg_id="def-1"))
        self.assertEqual(self._approvals(), before)
        sent = self.adapter.provider.sent[-1]["payload"]
        self.assertTrue(sent.strip())
        for tok in ("1500", "4200", "1200"):
            self.assertNotIn(tok, sent)

    def test_mention_no_pricing_side_effects(self):
        before = self._approvals()
        self.coord.handle_whatsapp_webhook(
            webhook_body("what affects the price?", msg_id="men-1"))
        self.assertEqual(self._approvals(), before)


if __name__ == "__main__":
    unittest.main()
