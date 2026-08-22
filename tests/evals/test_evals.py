import json
import unittest
from pathlib import Path

from amancore.agents.research import ResearchAgent
from amancore.content.service import ContentService
from amancore.crm.service import CRMService
from amancore.services.audit import AuditService
from amancore.services.content_approval import ContentApprovalService
from amancore.services.events import EventDispatcher
from amancore.skills.competitor_research import CompetitorResearchSkill
from amancore.skills.content_research import ContentResearchSkill
from amancore.skills.lead_research import LeadResearchSkill
from amancore.skills.research_source import FixtureResearchSource, RawResult
from tests.common import TempDirTestCase, make_brain, make_db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class LeadResearchEval(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.crm = CRMService(self.db)
        self.audit = AuditService(self.db)
        self.dispatcher = EventDispatcher()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_lead_research_fixtures(self):
        cases = json.loads((FIXTURES / "lead_research.json").read_text())["cases"]
        raw = [RawResult(title=c["title"], url=c["url"], source=c["source"]) for c in cases]
        source = FixtureResearchSource(raw)
        agent = ResearchAgent(
            self.brain, self.crm,
            LeadResearchSkill(source, router=None),
            CompetitorResearchSkill(source, router=None),
            ContentResearchSkill(source, router=None),
            audit=self.audit, dispatcher=self.dispatcher,
        )
        summary = agent.discover_leads("eval", "indonesia", limit=10)
        # case1 created, case2 duplicate, case3 rejected, case4 created (low)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(summary["rejected"], 1)
        leads = self.crm.search_leads()
        self.assertEqual(len(leads), 2)
        newco = [l for l in leads if l["company"] == "NewCo Export"][0]
        import json as _json
        self.assertIn("low", _json.loads(newco["provenance"])["confidence"])


class ContentApprovalEval(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.brain = make_brain(self.tmp)
        self.svc = ContentApprovalService(self.brain)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_content_cases(self):
        cases = json.loads((FIXTURES / "content_cases.json").read_text())["cases"]
        expected_map = {
            "approved": ("approved", False),
            "review": ("review", False),
            "rejected": ("rejected", False),
            "review_owner": ("review", True),
        }
        for c in cases:
            d = self.svc.evaluate({"content_id": "eval", "body": c["body"]})
            exp_status, exp_owner = expected_map[c["expect"]]
            self.assertEqual(d["status"], exp_status, f"case: {c['body']}")
            self.assertEqual(d["needs_owner"], exp_owner, f"case: {c['body']}")


if __name__ == "__main__":
    unittest.main()
