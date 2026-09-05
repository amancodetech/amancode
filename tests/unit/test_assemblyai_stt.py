"""AssemblyAI STT + DeepSeek continuation — offline only (mocked HTTP)."""

import unittest
from unittest.mock import MagicMock, patch


def _resp(status=200, payload=None):
    m = MagicMock(status_code=status)
    m.json.return_value = payload or {}
    m.text = str(payload)[:200]
    return m


class AssemblyAITranscriberTest(unittest.TestCase):
    def setUp(self):
        import os

        os.environ["ASSEMBLYAI_API_KEY"] = "test-key"
        os.environ["ASSEMBLYAI_BASE_URL"] = "https://api.assemblyai.com"

    def test_transcribe_arabic_flow(self):
        from amancore.voice.assemblyai import AssemblyAITranscriber

        tr = AssemblyAITranscriber(poll_interval_s=0)
        with patch("requests.post") as post, patch("requests.get") as get:
            post.side_effect = [
                _resp(200, {"upload_url": "https://cdn.assemblyai.com/upload/x"}),
                _resp(200, {"id": "tid123", "status": "queued"}),
            ]
            get.side_effect = [
                _resp(200, {"status": "processing"}),
                _resp(200, {
                    "status": "completed", "text": "مرحبا أريد متجرا",
                    "language_code": "ar", "confidence": 0.97,
                    "audio_duration": 5,
                }),
            ]
            res = tr.transcribe(b"OGG" + b"\x00" * 100)
            self.assertEqual(res.text, "مرحبا أريد متجرا")
            self.assertEqual(res.transcript_id, "tid123")
            self.assertEqual(res.language_code, "ar")
            # submit payload must pin Arabic
            submit_json = post.call_args_list[1][1]["json"]
            self.assertEqual(submit_json["language_code"], "ar")
            self.assertTrue(submit_json["punctuate"])
            # auth header is raw key (no Bearer)
            self.assertEqual(
                post.call_args_list[0][1]["headers"]["authorization"], "test-key"
            )

    def test_empty_bytes_rejected(self):
        from amancore.voice.assemblyai import AssemblyAITranscriber

        with self.assertRaises(ValueError):
            AssemblyAITranscriber().transcribe(b"")

    def test_error_status_raises(self):
        from amancore.voice.assemblyai import AssemblyAITranscriber

        tr = AssemblyAITranscriber(poll_interval_s=0)
        with patch("requests.post") as post, patch("requests.get") as get:
            post.side_effect = [
                _resp(200, {"upload_url": "https://cdn.assemblyai.com/upload/x"}),
                _resp(200, {"id": "tid9", "status": "queued"}),
            ]
            get.return_value = _resp(200, {"status": "error", "error": "bad audio"})
            with self.assertRaises(RuntimeError):
                tr.transcribe(b"12345")

    def test_missing_key_raises(self):
        import os

        from amancore.voice.assemblyai import AssemblyAITranscriber

        os.environ.pop("ASSEMBLYAI_API_KEY", None)
        with self.assertRaises(RuntimeError):
            AssemblyAITranscriber().transcribe(b"12345")


class DeepSeekContinueTest(unittest.TestCase):
    def setUp(self):
        import os

        os.environ["DEEPSEEK_API_KEY"] = "ds-test"
        os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"

    def test_continue_uses_deepseek_chat_by_default(self):
        from amancore.voice.pipeline import continue_with_deepseek

        with patch("requests.post") as post:
            post.return_value = _resp(200, {
                "choices": [{"message": {"content": "أهلا بك في أمان كود"}}]
            })
            out = continue_with_deepseek("أريد موقعا")
            self.assertIn("أمان كود", out)
            payload = post.call_args[1]["json"]
            self.assertEqual(payload["model"], "deepseek-chat")
            self.assertEqual(payload["max_tokens"], 1024)
            roles = [m["role"] for m in payload["messages"]]
            self.assertEqual(roles, ["system", "user"])
            self.assertEqual(post.call_count, 1)

    def test_honors_explicit_model_override(self):
        from amancore.voice.pipeline import continue_with_deepseek

        with patch("requests.post") as post:
            post.return_value = _resp(200, {
                "choices": [{"message": {"content": "رد"}}]
            })
            out = continue_with_deepseek("test", chat_model="deepseek-v4-flash-vision-exp", max_tokens=500)
            self.assertEqual(out, "رد")
            payload = post.call_args[1]["json"]
            self.assertEqual(payload["model"], "deepseek-v4-flash-vision-exp")
            self.assertEqual(payload["max_tokens"], 500)

    def test_full_pipeline(self):
        from amancore.voice.pipeline import transcribe_and_continue

        with patch(
            "amancore.voice.assemblyai.AssemblyAITranscriber.transcribe"
        ) as stt, patch("requests.post") as post:
            fake = MagicMock(text="أريد متجر إلكتروني", transcript_id="t1")
            stt.return_value = fake
            post.return_value = _resp(200, {
                "choices": [{"message": {"content": "تمام، نبدأ"}}]
            })
            res = transcribe_and_continue(b"audio-bytes")
            self.assertEqual(res.transcript, "أريد متجر إلكتروني")
            self.assertEqual(res.reply, "تمام، نبدأ")


class VoiceProcessorRoutingTest(unittest.TestCase):
    def test_assemblyai_primary_gemini_fallback(self):
        import os

        from amancore.voice.processor import VoiceNoteProcessor

        os.environ["ASSEMBLYAI_API_KEY"] = "k"
        proc = VoiceNoteProcessor()
        with patch(
            "amancore.voice.assemblyai.AssemblyAITranscriber.transcribe_simple",
            return_value="نص من AssemblyAI",
        ):
            self.assertEqual(proc.transcribe(b"abc"), "نص من AssemblyAI")
        with patch(
            "amancore.voice.assemblyai.AssemblyAITranscriber.transcribe_simple",
            return_value="",
        ), patch.object(proc, "_transcribe_gemini", return_value="نص Gemini"):
            self.assertEqual(proc.transcribe(b"abc"), "نص Gemini")


if __name__ == "__main__":
    unittest.main()
