import unittest

from amancore.skills.localization import LocalizationSkill
from amancore.skills.social_content import SocialContentSkill
from tests.common import FakeRouter


class LocalizationTest(unittest.TestCase):
    def test_passthrough_without_router(self):
        skill = LocalizationSkill(router=None)
        r = skill.localize("Hello world", "indonesia", "id")
        self.assertEqual(r["text"], "Hello world")

    def test_localized_with_router(self):
        skill = LocalizationSkill(router=FakeRouter({"routine": "Halo dunia"}))
        r = skill.localize("Hello world", "indonesia", "id")
        self.assertEqual(r["text"], "Halo dunia")

    def test_high_risk_uses_reasoning(self):
        router = FakeRouter({"reasoning": "Lokal"} )
        skill = LocalizationSkill(router=router)
        skill.localize("Pricing starts at $100", "gcc", "ar", high_risk=True)
        self.assertEqual(router.calls[0][0], "reasoning")


class SocialContentTest(unittest.TestCase):
    def test_generates_all_formats(self):
        skill = SocialContentSkill(router=None)
        formats = skill.generate("topic", "angle", "hook", "indonesia", "id", cta="Book now")
        self.assertEqual(len(formats), 6)
        self.assertIn("linkedin_post", formats)
        self.assertIn("tiktok_script", formats)
        self.assertEqual(formats["linkedin_post"]["platform"], "linkedin")


if __name__ == "__main__":
    unittest.main()
