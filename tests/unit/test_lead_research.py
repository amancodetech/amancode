import unittest

from amancore.skills.lead_research import (
    LeadResearchSkill,
    confidence_from_source,
)
from amancore.skills.research_source import FixtureResearchSource, RawResult
from tests.common import FakeRouter


class LeadResearchTest(unittest.TestCase):
    def test_confidence_mapping(self):
        self.assertEqual(confidence_from_source("official"), "high")
        self.assertEqual(confidence_from_source("directory"), "medium")
        self.assertEqual(confidence_from_source("inference"), "low")
        self.assertEqual(confidence_from_source("unknown"), "low")

    def test_discover_deterministic(self):
        source = FixtureResearchSource(
            [RawResult(title="Acme Trading", url="https://acme.co.id", source="directory")]
        )
        skill = LeadResearchSkill(source, router=None)
        results = skill.discover("trading", "indonesia", 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].company_name, "Acme Trading")
        self.assertEqual(results[0].website, "acme.co.id")
        self.assertEqual(results[0].confidence, "medium")

    def test_discover_with_router_extraction(self):
        source = FixtureResearchSource(
            [RawResult(title="x", url="https://acme.co.id", source="directory")]
        )
        router = FakeRouter(
            {"extraction": '{"company_name":"Acme","website":"acme.co.id","industry":"trading","confidence":"high"}'}
        )
        skill = LeadResearchSkill(source, router=router)
        results = skill.discover("trading", "indonesia", 5)
        self.assertEqual(results[0].company_name, "Acme")
        self.assertEqual(results[0].industry, "trading")
        self.assertEqual(results[0].confidence, "high")

    def test_empty_raw_returns_empty_result(self):
        source = FixtureResearchSource([RawResult(title="", url="")])
        skill = LeadResearchSkill(source, router=None)
        results = skill.discover("x", "indonesia", 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].company_name, "")
        self.assertEqual(results[0].website, "")

    def test_provenance_fields_present(self):
        source = FixtureResearchSource(
            [RawResult(title="Acme", url="https://acme.co.id", source="official")]
        )
        skill = LeadResearchSkill(source, router=None)
        r = skill.discover("x", "indonesia", 1)[0]
        self.assertTrue(r.source_url)
        self.assertTrue(r.retrieved_at)
        self.assertEqual(r.source, "official")


if __name__ == "__main__":
    unittest.main()
