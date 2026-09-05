"""Vision processor unit tests — offline only (no network)."""

import base64
import unittest

from amancore.vision.processor import (
    MAX_IMAGE_BYTES,
    VISION_MODEL,
    build_vision_messages,
    detect_image_mime,
)


class VisionFormatTest(unittest.TestCase):
    def test_detect_jpeg(self):
        self.assertEqual(
            detect_image_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 10), "image/jpeg"
        )

    def test_detect_png(self):
        self.assertEqual(
            detect_image_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10), "image/png"
        )

    def test_detect_gif87(self):
        self.assertEqual(detect_image_mime(b"GIF87a" + b"\x00" * 10), "image/gif")

    def test_detect_gif89(self):
        self.assertEqual(detect_image_mime(b"GIF89a" + b"\x00" * 10), "image/gif")

    def test_detect_webp(self):
        self.assertEqual(
            detect_image_mime(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10),
            "image/webp",
        )

    def test_reject_bmp_by_content(self):
        # renaming .bmp -> .png must NOT pass: detection is by bytes
        self.assertIsNone(detect_image_mime(b"BM" + b"\x00" * 20))

    def test_reject_empty(self):
        self.assertIsNone(detect_image_mime(b""))

    def test_reject_pdf(self):
        self.assertIsNone(detect_image_mime(b"%PDF-1.4 fake"))


class VisionMessagesTest(unittest.TestCase):
    def test_base64_user_only(self):
        b64 = base64.b64encode(b"\xff\xd8\xff fake-jpeg").decode()
        msgs = build_vision_messages(
            prompt="صف الصورة", image_b64=b64, mime="image/jpeg"
        )
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        content = msgs[0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "صف الصورة"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(
            content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        )
        self.assertEqual(content[1]["image_url"]["detail"], "high")

    def test_url_ok(self):
        msgs = build_vision_messages(
            prompt="x", image_url="https://example.com/a.png"
        )
        self.assertEqual(
            msgs[0]["content"][1]["image_url"]["url"], "https://example.com/a.png"
        )

    def test_rejects_both_transports(self):
        with self.assertRaises(ValueError):
            build_vision_messages(
                prompt="x",
                image_b64="aaa",
                mime="image/png",
                image_url="https://example.com/a.png",
            )

    def test_rejects_unsupported_mime(self):
        with self.assertRaises(ValueError):
            build_vision_messages(prompt="x", image_b64="aaa", mime="image/bmp")

    def test_rejects_non_http_url(self):
        with self.assertRaises(ValueError):
            build_vision_messages(prompt="x", image_url="file:///etc/passwd")


class VisionServiceValidationTest(unittest.TestCase):
    def test_empty_bytes_rejected(self):
        from amancore.vision.processor import ImageUnderstandingService

        svc = ImageUnderstandingService(api_key="dummy")
        with self.assertRaises(ValueError):
            svc.describe(b"")

    def test_oversize_rejected_before_network(self):
        from amancore.vision.processor import ImageUnderstandingService

        svc = ImageUnderstandingService(api_key="dummy")
        big = b"\xff\xd8\xff" + b"\x00" * (MAX_IMAGE_BYTES + 1)
        with self.assertRaises(ValueError) as ctx:
            svc.describe(big)
        self.assertIn("32 MiB", str(ctx.exception))

    def test_unsupported_bytes_rejected_before_network(self):
        from amancore.vision.processor import ImageUnderstandingService

        svc = ImageUnderstandingService(api_key="dummy")
        with self.assertRaises(ValueError) as ctx:
            svc.describe(b"BM" + b"\x00" * 100)
        self.assertIn("JPEG/PNG/GIF/WebP", str(ctx.exception))

    def test_default_model_id(self):
        self.assertEqual(VISION_MODEL, "deepseek-v4-flash-vision-exp")


if __name__ == "__main__":
    unittest.main()
