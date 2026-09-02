"""VoiceNoteProcessor — converts customer voice notes into text using Gemini Multimodal Audio.

Supports:
- WhatsApp voice notes (.ogg / opus)
- Telegram voice notes and audio messages
- Arabic dialects (Gulf, Egyptian, Levantine, Yemeni, etc.) + Technical terms
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from ..log import get_logger

log = get_logger("voice.processor")

VOICE_PROMPT = (
    "أنت خبير تفريغ وفهم الرسائل والتسجيلات الصوتية بدقة متناهية. "
    "قم بتفريغ هذا المقطع الصوتي بدقة باللغة العربية مع فهم اللهجات المحلية (خليجية، مصرية، شامية، يمنية، فصحى) "
    "والمصطلحات التقنية والبرمجية. "
    "أخرج النص المفرغ فقط بدون أي مقدمات أو شروحات أو تعليقات."
)


class VoiceNoteProcessor:
    """Processes and transcribes voice notes via Gemini Audio Multimodal API."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def transcribe(self, audio_data: bytes, mime_type: str = "audio/ogg") -> str:
        """Transcribes raw audio bytes into text."""
        if not audio_data:
            return ""

        if not self.api_key:
            log.warning("cannot transcribe voice note: GEMINI_API_KEY not set")
            return ""

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            model_id = os.environ.get("AMANCODE_MODEL_DEFAULT", "gemini-2.5-flash")

            part = types.Part.from_bytes(data=audio_data, mime_type=mime_type)
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=VOICE_PROMPT), part],
                    )
                ],
                config=types.GenerateContentConfig(temperature=0.1),
            )
            text = (response.text or "").strip()
            log.info("transcribed voice note successfully (chars=%d)", len(text))
            return text
        except Exception as exc:
            log.error("failed transcribing audio with gemini: %s", exc)
            return ""

    def transcribe_file(self, file_path: str | Path) -> str:
        """Transcribes an audio file from disk."""
        path = Path(file_path)
        if not path.exists():
            log.error("audio file not found: %s", file_path)
            return ""

        mime_map = {
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
            ".mp3": "audio/mp3",
            ".m4a": "audio/m4a",
            ".wav": "audio/wav",
        }
        mime_type = mime_map.get(path.suffix.lower(), "audio/ogg")
        with open(path, "rb") as f:
            audio_bytes = f.read()
        return self.transcribe(audio_bytes, mime_type=mime_type)
