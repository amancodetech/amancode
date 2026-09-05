"""Price-intent 3-class — locks D8 approved lists (CH-01). Pure function, no I/O."""

import unittest

from amancore.channels.coordinator import classify_price_intent


class PriceIntentTest(unittest.TestCase):
    def test_direct_ask_en(self):
        for t in ["what is the price?", "how much does it cost?",
                  "give me an estimate", "send me a quote please",
                  "what is the approximate cost?"]:
            self.assertEqual(classify_price_intent(t), "direct_ask", t)

    def test_direct_ask_ar_id(self):
        for t in ["بكم الموقع؟", "كم سعر الموقع", "كم تكلف؟",
                  "كم سيكلفني؟", "طيب كم صار السعر الآن؟",
                  "أرسل عرض سعر", "berapa harga?", "minta quote dong"]:
            self.assertEqual(classify_price_intent(t), "direct_ask", t)

    def test_deferral_never_dispatches(self):
        for t in ["we can discuss the price later",
                  "price is not important now",
                  "السعر لاحقا نتكلم فيه",
                  "مو وقت السعر الآن",
                  "nanti saja soal harga",
                  "belum perlu harga sekarang"]:
            self.assertEqual(classify_price_intent(t), "deferral", t)

    def test_mention_continues_discovery(self):
        for t in ["what affects the price?", "I already know the price",
                  "how much?"]:
            self.assertEqual(classify_price_intent(t), "mention", t)

    def test_none_for_non_price(self):
        for t in ["my budget is 10000", "I want a website",
                  "متى التسليم؟", "saya mau website"]:
            self.assertEqual(classify_price_intent(t), "none", t)

    def test_classifier_never_raises(self):
        for t in ["", None, "   ", "12345"]:
            self.assertIn(classify_price_intent(t),
                          ("direct_ask", "deferral", "mention", "none"))


if __name__ == "__main__":
    unittest.main()
