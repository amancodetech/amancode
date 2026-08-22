import unittest

from amancore.skills.competitor_research import CompetitorResearchSkill
from amancore.skills.research_source import FixtureResearchSource


class CompetitorResearchTest(unittest.TestCase):
    def test_pricing_not_invented(self):
        skill = CompetitorResearchSkill(FixtureResearchSource([]), router=None)
        result = skill.analyze("Acme", "https://acme.co.id", "indonesia")
        self.assertEqual(result["pricing_visible"], "not_publicly_available")
        self.assertEqual(result["name"], "Acme")

    def test_no_fabricated_clients_or_revenue(self):
        skill = CompetitorResearchSkill(FixtureResearchSource([]), router=None)
        result = skill.analyze("Acme")
        self.assertNotIn("clients", result)
        self.assertNotIn("revenue", result)


if __name__ == "__main__":
    unittest.main()
