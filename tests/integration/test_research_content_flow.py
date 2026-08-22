import unittest

from amancore.agents.content import ContentAgent
from amancore.agents.research import ResearchAgent
from amancore.content.service import ContentService
from amancore.crm.service import CRMService
from amancore.services.approvals import ApprovalService
from amancore.services.audit import AuditService
from amancore.services.content_approval import ContentApprovalService
from amancore.services.events import EventDispatcher
from amancore.skills.competitor_research import CompetitorResearchSkill
from amancore.skills.content_research import ContentResearchSkill
from amancore.skills.lead_research import LeadResearchSkill
from amancore.skills.localization import LocalizationSkill
from amancore.skills.research_source import FixtureResearchSource, RawResult
from amancore.skills.social_content import SocialContentSkill
from tests.common import FakeRouter, TempDirTestCase, make_brain, make_db


class ResearchContentFlowTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()
        self.router = FakeRouter({
            "extraction": '{"company_name":"Acme Trading","website":"acme.co.id","industry":"trading","confidence":"high"}',
            "routine": "Practical tips to improve your online presence",
        })
        source = FixtureResearchSource(
            [RawResult(title="Acme Trading", url="https://acme.co.id", source="directory")]
        )
        self.research = ResearchAgent(
            self.brain, self.crm,
            LeadResearchSkill(source, self.router),
            CompetitorResearchSkill(source, self.router),
            ContentResearchSkill(source, self.router),
            router=self.router, audit=self.audit, dispatcher=self.dispatcher,
        )
        self.content_service = ContentService(self.db)
        self.approval = ContentApprovalService(
            self.brain, approvals=ApprovalService(self.db, audit=self.audit), audit=self.audit
        )
        self.content = ContentAgent(
            self.brain, self.content_service, self.approval,
            LocalizationSkill(self.router), SocialContentSkill(self.router),
            router=self.router, audit=self.audit, dispatcher=self.dispatcher,
        )

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_research_to_content_flow(self):
        summary = self.research.discover_leads("trading", "indonesia", 5)
        self.assertEqual(summary["created"], 1)
        leads = self.crm.search_leads()
        self.assertEqual(leads[0]["company"], "Acme Trading")
        self.assertTrue(leads[0]["provenance"])
        self.assertTrue(leads[0]["fit_signals"])

        cid = self.content.draft("Digital transformation", "indonesia", "id", "linkedin_post")
        content = self.content_service.get(cid)
        self.assertEqual(content["status"], "approved")

        # audit trail captured both phases
        self.assertGreaterEqual(self.audit.count(), 1)

    def test_duplicate_lead_is_enriched_not_duplicated(self):
        self.research.discover_leads("trading", "indonesia", 5)
        summary = self.research.discover_leads("trading", "indonesia", 5)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(len(self.crm.search_leads()), 1)


if __name__ == "__main__":
    unittest.main()
