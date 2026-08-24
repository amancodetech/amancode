import unittest
from pathlib import Path

import yaml

from amancore.agents.sales import SalesAgent
from amancore.agents.support import SupportAgent
from amancore.channels.coordinator import MessageCoordinator
from amancore.channels.handover import HandoverService
from amancore.channels.language import LanguageDetector
from amancore.channels.outbox import MessageOutbox, OutboxWorker
from amancore.channels.policy import ChannelPolicyEngine
from amancore.channels.response_filter import ExternalResponseFilter
from amancore.channels.whatsapp import WhatsAppAdapter
from amancore.crm.service import CRMService
from amancore.ops.smoke import SmokeTestService, TEST_WA_ID
from amancore.pricing.proposal import ProposalStore
from amancore.pricing.snapshot import PricingSnapshotStore
from amancore.sales.conversation_memory import ConversationMemory
from amancore.sales.discovery import DiscoveryEngine
from amancore.sales.followup import FollowupEngine
from amancore.sales.handoff import HandoffService
from amancore.sales.qualification import QualificationEngine
from amancore.services.events import EventDispatcher, IdempotencyStore
from amancore.skills.localization import LocalizationSkill
from amancore.skills.objection_handling import ObjectionHandlingSkill
from amancore.support.cases import SupportCaseStore
from tests.common import TempDirTestCase, make_brain, make_db

ROOT = Path(__file__).resolve().parent.parent.parent


class SmokeTestServiceTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.dispatcher = EventDispatcher()
        self.adapter = WhatsAppAdapter({"mode": "mock", "signature_required": False})
        self.outbox = MessageOutbox(self.db)
        policy = ChannelPolicyEngine(self.brain)
        self.worker = OutboxWorker(self.outbox, {"whatsapp": self.adapter}, policy, dispatcher=self.dispatcher)
        memory = ConversationMemory(self.crm)
        sales = SalesAgent(
            self.brain, self.crm, memory, DiscoveryEngine(), QualificationEngine(),
            ObjectionHandlingSkill(self.brain), FollowupEngine(), HandoffService(self.dispatcher),
            router=None, dispatcher=self.dispatcher,
        )
        support_policy = yaml.safe_load((ROOT / "configs" / "support.yaml").read_text(encoding="utf-8"))
        support = SupportAgent(
            self.brain, self.crm, SupportCaseStore(self.db), HandoverService(self.crm, self.dispatcher),
            owner_alert=lambda *a, **kw: None, support_policy=support_policy,
        )
        self.coord = MessageCoordinator(
            self.adapter, self.outbox, self.worker, sales, self.crm, memory,
            HandoverService(self.crm, self.dispatcher), ExternalResponseFilter(), policy,
            IdempotencyStore(self.db), LanguageDetector(), LocalizationSkill(router=None),
            PricingSnapshotStore(self.db), ProposalStore(self.db),
            owner_alert=lambda *a, **kw: None, dispatcher=self.dispatcher, support_agent=support,
        )
        self.smoke = SmokeTestService(self.coord, self.crm, self.adapter)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_smoke_all_pass(self):
        result = self.smoke.run()
        self.assertEqual(result["status"], "PASS")
        for name, t in result["tests"].items():
            self.assertEqual(t["status"], "PASS", name)

    def test_smoke_uses_test_number_only(self):
        self.smoke.run()
        sent_to = {m["to"] for m in self.adapter.provider.sent}
        self.assertEqual(sent_to, {TEST_WA_ID})
        leads = self.crm.search_leads(limit=100)
        self.assertTrue(all(l["contact_whatsapp"] == TEST_WA_ID for l in leads))


class ProductionGateExtendedTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _config(self, **flags):
        ov = {
            "api_docs_verified": False, "account_configuration_verified": False,
            "business_verification_complete": False, "phone_number_configured": False,
            "webhook_reachable": False, "webhook_verified": False, "signature_tested": False,
            "outbound_tested": False, "template_requirements_satisfied": False,
            "optout_tested": False, "human_takeover_tested": False, "idempotency_tested": False,
            "outbox_tested": False, "policy_tested": False, "audit_tested": False,
            "health_pass": False, "owner_alert_configured": False, "secrets_configured": False,
            "backup_verified": False, "recovery_test_passed": False, "runbooks_exist": False,
            "alert_transport_works": False, "owner_destination_configured": False,
        }
        ov.update(flags)
        return {
            "environment": {"mode": "mock", "production_enabled": False, "webhook_url": ""},
            "official_verification": {"status": "PENDING", **ov},
        }

    def test_disabled_by_default_never_ready(self):
        from amancore.production.gate import ProductionGateService

        report = ProductionGateService(self._config(), db=self.db, env={}).check()
        self.assertEqual(report["verdict"], "NOT_READY")
        self.assertFalse(report["production_enabled"])

    def test_operational_gates_present(self):
        from amancore.production.gate import ProductionGateService

        report = ProductionGateService(self._config(), db=self.db, env={}).check()
        gate_names = {g["gate"] for g in report["gates"]}
        for gate in ("backup_verified", "recovery_test_passed", "runbooks_exist",
                     "alert_transport_works", "owner_destination_configured",
                     "database_integrity", "runbooks_present"):
            self.assertIn(gate, gate_names)

    def test_database_integrity_gate(self):
        from amancore.production.gate import ProductionGateService

        report = ProductionGateService(self._config(), db=self.db, env={}).check()
        db_gate = [g for g in report["gates"] if g["gate"] == "database_integrity"][0]
        self.assertEqual(db_gate["status"], "PASS")

    def test_ready_only_when_everything_passes(self):
        from amancore.production.gate import ProductionGateService

        cfg = self._config(
            api_docs_verified=True, account_configuration_verified=True,
            business_verification_complete=True, phone_number_configured=True,
            webhook_reachable=True, webhook_verified=True, signature_tested=True,
            outbound_tested=True, template_requirements_satisfied=True,
            optout_tested=True, human_takeover_tested=True, idempotency_tested=True,
            outbox_tested=True, policy_tested=True, audit_tested=True,
            health_pass=True, owner_alert_configured=True, secrets_configured=True,
            backup_verified=True, recovery_test_passed=True, runbooks_exist=True,
            alert_transport_works=True, owner_destination_configured=True,
        )
        cfg["environment"] = {"mode": "production", "production_enabled": True,
                              "webhook_url": "https://example.com/w"}
        secrets = {
            "WHATSAPP_VERIFY_TOKEN": "t", "WHATSAPP_APP_SECRET": "s",
            "WHATSAPP_ACCESS_TOKEN": "a", "WHATSAPP_PHONE_NUMBER_ID": "p",
        }
        # runbooks must exist for runbooks_present
        runbooks = self.tmp / "docs" / "runbooks"
        runbooks.mkdir(parents=True)
        for i in range(10):
            (runbooks / f"{i:02d}.md").write_text("# runbook")
        cfg["_root"] = self.tmp
        import os

        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
        os.environ["TELEGRAM_CHAT_ID"] = "test-chat"
        try:
            report = ProductionGateService(cfg, db=self.db, env=secrets).check()
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        self.assertEqual(report["verdict"], "READY")


if __name__ == "__main__":
    unittest.main()
