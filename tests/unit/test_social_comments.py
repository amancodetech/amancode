import sqlite3
import unittest
from amancore.social.comment_engine import SocialCommentEngine

class TestSocialCommentEngine(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        with open("/home/omar/Desktop/work/aman-core/amancore/storage/schema.sql") as f:
            self.con.executescript(f.read())
        self.engine = SocialCommentEngine(db=self.con)

    def tearDown(self):
        self.con.close()

    def test_pricing_inquiry_analysis(self):
        res = self.engine.analyze_comment(
            channel="instagram",
            comment_text="كم سعر تصميم هوية بصرية كاملة مع لوجو؟",
            commenter_name="أحمد"
        )
        self.assertEqual(res["intent"], "INQUIRY_PRICING")
        self.assertFalse(res["is_offensive"])
        self.assertTrue(res["should_like"])
        self.assertIn("أحمد", res["public_reply"])
        self.assertIsNotNone(res["dm_message"])

    def test_praise_comment(self):
        res = self.engine.analyze_comment(
            channel="facebook",
            comment_text="عمل رائع جدا ما شاء الله بالتوفيق",
            commenter_name="محمود"
        )
        self.assertEqual(res["intent"], "PRAISE")
        self.assertFalse(res["is_offensive"])
        self.assertTrue(res["should_like"])

    def test_offensive_spam_filtering(self):
        res = self.engine.analyze_comment(
            channel="tiktok",
            comment_text="شركة نصابين حرامية لا احد يشتري منهم scam",
            commenter_name="مخرب"
        )
        self.assertTrue(res["is_offensive"])
        self.assertFalse(res["should_like"])
        self.assertIn(res["action"], ("HIDE", "DELETE"))

    def test_record_comment_db(self):
        analysis = {
            "intent": "INQUIRY_SERVICE",
            "sentiment": "positive",
            "is_offensive": False,
            "public_reply": "أهلاً بك! تم الرد",
            "dm_message": "تفاصيل الخدمة",
            "action": "REPLY_AND_DM"
        }
        ok = self.engine.record_comment(
            channel="instagram",
            comment_id="comm_test_123",
            comment_text="أريد موقع تعريفي",
            analysis=analysis,
            commenter_name="سالم"
        )
        self.assertTrue(ok)
        row = self.con.execute("SELECT * FROM social_comments WHERE comment_id='comm_test_123'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["commenter_name"], "سالم")
        self.assertEqual(row["action_taken"], "REPLY_AND_DM")

if __name__ == "__main__":
    unittest.main()
