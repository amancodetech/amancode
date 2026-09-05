"""Email channel unit tests — offline only (mocked SMTP/IMAP)."""

import unittest
from unittest.mock import MagicMock, patch


class EmailNormalizeTest(unittest.TestCase):
    def test_lowercase(self):
        from amancore.channels.email import normalize_email

        self.assertEqual(normalize_email("Client@Example.COM "), "client@example.com")

    def test_invalid_raises(self):
        from amancore.channels.email import normalize_email

        for bad in ("", "not-an-email", "a@b", "@x.com", "a b@c.com"):
            with self.assertRaises(ValueError):
                normalize_email(bad)


class EmailAdapterInboundTest(unittest.TestCase):
    def test_receive_webhook_parses(self):
        from amancore.channels.email import EmailAdapter

        body = {"emails": [
            {"from": "Client@Example.com", "subject": "سؤال عن متجر",
             "text": "بكم المتجر؟", "message_id": "<abc123@mail>",
             "date": "Thu, 04 Sep 2026 10:00:00 +0000"},
            {"from": "bad-address", "text": "skip me"},
        ]}
        events = EmailAdapter({}).receive_webhook(body)
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt.channel, "email")
        self.assertEqual(evt.payload["external_user_id"], "client@example.com")
        self.assertEqual(evt.payload["message_type"], "text")
        self.assertEqual(evt.payload["text"], "بكم المتجر؟")
        self.assertEqual(evt.idempotency_key, "em:<abc123@mail>")
        self.assertEqual(evt.metadata["subject"], "سؤال عن متجر")

    def test_idempotent_without_message_id(self):
        from amancore.channels.email import EmailAdapter

        body = {"emails": [{"from": "a@b.com", "text": "hi"}]}
        e1 = EmailAdapter({}).receive_webhook(body)[0]
        e2 = EmailAdapter({}).receive_webhook(body)[0]
        self.assertTrue(e1.idempotency_key.startswith("em:"))
        self.assertEqual(e1.idempotency_key, e2.idempotency_key)

    def test_capabilities_text_only(self):
        from amancore.channels.email import EmailAdapter

        caps = EmailAdapter({}).capabilities()
        self.assertTrue(caps.text)
        self.assertFalse(caps.image)


class EmailAdapterSendTest(unittest.TestCase):
    def test_send_text_uses_smtp(self):
        import os

        from amancore.channels.email import EmailAdapter

        os.environ.update({"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
                           "SMTP_USER": "bot@example.com", "SMTP_PASSWORD": "pw"})
        with patch("smtplib.SMTP") as smtp:
            res = EmailAdapter({"mode": "mock"}).send(
                "Client@Example.com", "text", "مرحبا")
            self.assertEqual(res["status"], "sent")
            server = smtp.return_value.__enter__.return_value
            server.login.assert_called_once_with("bot@example.com", "pw")
            sent = server.sendmail.call_args[0]
            self.assertEqual(sent[1], ["client@example.com"])

    def test_send_email_with_ics(self):
        import os

        from amancore.channels.email import EmailAdapter

        os.environ.update({"SMTP_HOST": "smtp.example.com",
                           "SMTP_USER": "bot@example.com", "SMTP_PASSWORD": "pw"})
        with patch("smtplib.SMTP") as smtp:
            EmailAdapter({"mode": "mock"}).send("a@b.com", "email", {
                "subject": "Invite", "body": "see you",
                "ics": "BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            })
            raw = smtp.return_value.__enter__.return_value.sendmail.call_args[0][2]
            self.assertIn("text/calendar", raw)
            self.assertIn("Invite", raw)

    def test_send_rejects_bad_recipient(self):
        from amancore.channels.email import EmailAdapter

        with self.assertRaises(ValueError):
            EmailAdapter({}).send("not-an-email", "text", "hi")


class EmailPollParseTest(unittest.TestCase):
    def test_parse_plain_message(self):
        from amancore.channels.email_poll import parse_message

        raw = (b"From: Sara <Sara@Example.com>\r\n"
               b"Subject: =?UTF-8?B?2KfZhNiz2YjYpw==?=\r\n"
               b"Message-ID: <xyz@mail>\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
               b"Hello there")
        item = parse_message(raw)
        self.assertEqual(item["from"], "sara@example.com")
        self.assertEqual(item["message_id"], "xyz@mail")
        self.assertIn("Hello", item["text"])

    def test_parse_skips_missing_from(self):
        from amancore.channels.email_poll import parse_message

        self.assertIsNone(parse_message(b"Subject: x\r\n\r\nbody"))


class EmailResolverTest(unittest.TestCase):
    def test_resolver_knows_email(self):
        from amancore.channels.provider_resolver import (
            build_channel_adapter,
            resolve_channel_config,
        )

        cfg = resolve_channel_config(
            "email", {"email": {"mode": "mock", "enabled": True}}, {})
        self.assertIsNotNone(cfg)
        adapter = build_channel_adapter("email", cfg)
        self.assertEqual(adapter.channel, "email")


if __name__ == "__main__":
    unittest.main()
