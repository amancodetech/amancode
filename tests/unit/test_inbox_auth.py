"""Unit tests for the private owner inbox security primitives (Phase 3L)."""

import time
import unittest

from amancore.channels.inbox import (
    LoginRateLimiter,
    extract_session_cookie,
    hash_password,
    make_session_token,
    render_login_page,
    render_inbox_page,
    verify_password,
    verify_session_token,
)


class TestPasswordHashing(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self):
        stored = hash_password("s3cret-password")
        self.assertTrue(stored.startswith("pbkdf2$"))
        self.assertTrue(verify_password("s3cret-password", stored))

    def test_wrong_password_rejected(self):
        stored = hash_password("correct")
        self.assertFalse(verify_password("incorrect", stored))

    def test_salts_are_unique(self):
        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_malformed_stored_value_is_safe(self):
        self.assertFalse(verify_password("x", "garbage"))
        self.assertFalse(verify_password("x", ""))
        self.assertFalse(verify_password("x", "md5$1$aa$bb"))


class TestSessionTokens(unittest.TestCase):
    def setUp(self):
        self.secret = "a" * 32

    def test_valid_token_accepted(self):
        token = make_session_token(self.secret)
        self.assertTrue(verify_session_token(self.secret, token))

    def test_expired_token_rejected(self):
        long_ago = time.time() - 12 * 60 * 60 - 10  # beyond SESSION_TTL
        token = make_session_token(self.secret, now=long_ago)
        self.assertFalse(verify_session_token(self.secret, token))

    def test_wrong_secret_rejected(self):
        token = make_session_token(self.secret)
        self.assertFalse(verify_session_token("b" * 32, token))

    def test_tampered_payload_rejected(self):
        token = make_session_token(self.secret)
        tampered = token.replace(".", ".9", 1) if "." in token else token + "x"
        self.assertFalse(verify_session_token(self.secret, tampered))

    def test_malformed_tokens_rejected(self):
        for bad in (None, "", "no-dots", "a.b", "x.y.z.extra"):
            self.assertFalse(verify_session_token(self.secret, bad))


class TestCookieExtraction(unittest.TestCase):
    def test_extract_present(self):
        header = "other=1; amancore_inbox=tok123; x=y"
        self.assertEqual(extract_session_cookie(header), "tok123")

    def test_extract_missing(self):
        self.assertIsNone(extract_session_cookie(None))
        self.assertIsNone(extract_session_cookie("other=1"))
        self.assertIsNone(extract_session_cookie(";;;bad;;"))


class TestLoginRateLimiter(unittest.TestCase):
    def test_locks_after_threshold(self):
        limiter = LoginRateLimiter(max_failures=3, window_seconds=60)
        for _ in range(2):
            limiter.record_failure("ip1")
            self.assertFalse(limiter.is_locked("ip1"))
        limiter.record_failure("ip1")
        self.assertTrue(limiter.is_locked("ip1"))

    def test_window_expiry_unlocks(self):
        limiter = LoginRateLimiter(max_failures=2, window_seconds=60)
        limiter.record_failure("ip1", now=1000.0)
        limiter.record_failure("ip1", now=1001.0)
        self.assertTrue(limiter.is_locked("ip1", now=1002.0))
        self.assertFalse(limiter.is_locked("ip1", now=1100.0))

    def test_keys_are_isolated(self):
        limiter = LoginRateLimiter(max_failures=1, window_seconds=60)
        limiter.record_failure("ip1")
        self.assertTrue(limiter.is_locked("ip1"))
        self.assertFalse(limiter.is_locked("ip2"))


class TestInboxRendering(unittest.TestCase):
    def test_login_page_escapes_error(self):
        page = render_login_page("/ibx/login", "<script>alert(1)</script>")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_inbox_page_uses_base_paths(self):
        page = render_inbox_page("/ibx-abc", "/ibx-abc/logout")
        self.assertIn('action="/ibx-abc/logout"', page)
        self.assertIn("/ibx-abc/api/leads", page)


if __name__ == "__main__":
    unittest.main()
