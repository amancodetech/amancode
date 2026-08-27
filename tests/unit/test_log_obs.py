"""OBS-101: logging wiring, secret redaction, correlation binding."""

import io
import logging
import unittest


class TestSecretRedaction(unittest.TestCase):
    def _filtered_message(self, msg: str) -> str:
        from amancore.log import SecretRedactionFilter

        record = logging.LogRecord(
            "amancore.test", logging.INFO, "x", 1, msg, None, None)
        SecretRedactionFilter().filter(record)
        return record.getMessage()

    def test_token_value_redacted(self):
        out = self._filtered_message("send failed token=abc123XYZ retrying")
        self.assertNotIn("abc123XYZ", out)
        self.assertIn("<redacted>", out)

    def test_colon_style_redacted(self):
        out = self._filtered_message("auth: Bearer eyJhbGciOi.9fjw")
        self.assertNotIn("eyJhbGciOi", out)

    def test_api_key_redacted(self):
        out = self._filtered_message("demo-provider api_key=sk-demo12345678")
        self.assertNotIn("sk-demo12345678", out)

    def test_normal_text_untouched(self):
        msg = "webhook received wa_id=905341112233 chars=12"
        self.assertEqual(self._filtered_message(msg), msg)

    def test_word_token_alone_not_mangled(self):
        out = self._filtered_message("token expired for lead 42")
        self.assertIn("token expired", out)


class TestCorrelationBinding(unittest.TestCase):
    def test_correlation_appears_in_output(self):
        from amancore.log import set_correlation_id, setup_logging

        setup_logging()
        root = logging.getLogger("amancore")
        stream = io.StringIO()
        root.handlers[0].stream = stream
        try:
            set_correlation_id("corr-test-123")
            root.info("hello forensic world")
        finally:
            set_correlation_id(None)
            root.handlers[0].stream = __import__("sys").stderr
        self.assertIn("cid=corr-test-123", stream.getvalue())
        self.assertIn("hello forensic world", stream.getvalue())


class TestSetupIdempotent(unittest.TestCase):
    def test_double_setup_single_handler(self):
        from amancore.log import StreamHandlerCompat, setup_logging

        before = len(logging.getLogger("amancore").handlers)
        setup_logging()
        setup_logging()
        handlers = logging.getLogger("amancore").handlers
        self.assertEqual(len(handlers), before)  # no growth
        compat = [h for h in handlers if isinstance(h, StreamHandlerCompat)]
        self.assertEqual(len(compat), 1)  # exactly one wired handler


if __name__ == "__main__":
    unittest.main()
