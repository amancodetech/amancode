import os
import unittest
from amancore.content.autopilot import ContentAutopilotEngine, WEEKLY_MATRIX

class TestContentAutopilotEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ContentAutopilotEngine()

    def test_weekly_matrix_complete(self):
        self.assertEqual(len(WEEKLY_MATRIX), 7)
        for i in range(7):
            theme = self.engine.get_today_theme(i)
            self.assertIn("category_name", theme)
            self.assertIn("badge", theme)
            self.assertIn("topic", theme)
            self.assertIn("accent", theme)

    def test_generate_content(self):
        content = self.engine.generate_content(day_of_week=0)
        self.assertIn("title", content)
        self.assertIn("subtitle", content)
        self.assertIn("caption", content)
        self.assertIn("theme", content)
        self.assertTrue(len(content["title"]) > 0)
        self.assertTrue(len(content["caption"]) > 10)

    def test_create_banner_renders_valid_image(self):
        content = self.engine.generate_content(day_of_week=1)
        theme = content["theme"]
        banner_path = self.engine.create_banner(
            title=content["title"],
            subtitle=content["subtitle"],
            badge=theme["badge"],
            accent_hex=theme["accent"]
        )
        self.assertTrue(os.path.exists(banner_path))
        self.assertTrue(os.path.getsize(banner_path) > 1000)

if __name__ == "__main__":
    unittest.main()
