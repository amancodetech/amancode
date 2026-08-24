"""Unit tests — Telegram owner console pure logic (no network)."""

import unittest

from amancore.ops.telegram_console import (
    HELP_TEXT,
    normalize_number,
    parse_slash,
)


class TestNormalizeNumber(unittest.TestCase):
    def test_strips_formatting(self):
        self.assertEqual(normalize_number("+90 534 242-25-65"), "905342422565")

    def test_no_silent_country_code_invention(self):
        # WA-302/W2: the old lstrip("0") corrupted local numbers by eating a
        # meaningful trunk zero — normalization now strips ONLY the literal
        # "00" international prefix, never a lone leading 0.
        self.assertEqual(normalize_number("081234567890"), "081234567890")

    def test_double_zero_international_prefix_still_stripped(self):
        self.assertEqual(normalize_number("00905321112233"), "905321112233")

    def test_empty(self):
        self.assertEqual(normalize_number(""), "")
        self.assertEqual(normalize_number(None), "")


class TestParseSlash(unittest.TestCase):
    def test_command_with_args(self):
        self.assertEqual(parse_slash("/send 90534 hi"), ("send", "90534 hi"))

    def test_command_bare(self):
        self.assertEqual(parse_slash("/status"), ("status", ""))

    def test_non_command_arabic(self):
        self.assertEqual(parse_slash("راسل العميل فلان"), (None, ""))

    def test_uppercase_normalised(self):
        self.assertEqual(parse_slash("/STATUS")[0], "status")


class TestHelpText(unittest.TestCase):
    def test_lists_core_commands(self):
        for token in ("/status", "/leads", "/customer", "/send", "/mode"):
            self.assertIn(token, HELP_TEXT)


if __name__ == "__main__":
    unittest.main()
