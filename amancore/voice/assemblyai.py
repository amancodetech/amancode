"""AssemblyAI Speech-to-Text — primary voice understanding for AmanCore.

Flow (pre-recorded, async):
  1. POST /v2/upload (raw bytes) -> upload_url   [local/WhatsApp ogg only]
  2. POST /v2/transcript {audio_url, language_code:'ar', ...} -> id
  3. GET  /v2/transcript/{id} every ~3s until completed/error

Auth: header `authorization: <KEY>` (NO Bearer prefix).
Key source: env ASSEMBLYAI_API_KEY only — never hardcode, never log.
Base: env ASSEMBLYAI_BASE_URL (default https://api.assemblyai.com).

Arabic: language_code='ar' by default (WhatsApp/Telegram voice notes
are Arabic dialects). Set language_code=None + language_detection=True
only when you truly need auto-detect (costs extra latency).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from ..log import get_logger

log = get_logger("voice.assemblyai")

DEFAULT_BASE_URL = "https://api.assemblyai.com"
DEFAULT_LANGUAGE = "ar"
POLL_INTERVAL_S = 3.0
DEFAULT_TIMEOUT_S = 300  # 5 min max per voice note (WhatsApp notes are short)
MAX_AUDIO_BYTES = 200 * 1024 * 1024  # safety cap well below 2.2GB upload limit


@dataclass
class AssemblyAIResult:
    text: str
    transcript_id: str = ""
    language_code: str = DEFAULT_LANGUAGE
    confidence: float | None = None
    audio_duration: int | None = None


def _api_key(explicit: str | None = None) -> str:
    key = (explicit or os.environ.get("ASSEMBLYAI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not configured")
    return key


def _base_url() -> str:
    return os.environ.get("ASSEMBLYAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _headers(api_key: str) -> dict:
    # NOTE: AssemblyAI uses raw key, NOT "Bearer <key>".
    return {"authorization": api_key}


class AssemblyAITranscriber:
    """Transcribe raw audio bytes via AssemblyAI (Arabic-first)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        language_code: str | None = DEFAULT_LANGUAGE,
        poll_interval_s: float = POLL_INTERVAL_S,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ):
        self._explicit_key = api_key
        if base_url is not None:
            os.environ["ASSEMBLYAI_BASE_URL"] = base_url
        env_lang = os.environ.get("ASSEMBLYAI_LANGUAGE_CODE", "").strip().lower()
        if language_code in ("auto", "detect") or (language_code is None and env_lang in ("auto", "detect")):
            self.language_code = None
        elif language_code == DEFAULT_LANGUAGE and env_lang in ("auto", "detect"):
            self.language_code = None
        else:
            self.language_code = language_code
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s

    def _upload(self, audio_data: bytes, api_key: str, base: str) -> str:
        import requests

        resp = requests.post(
            f"{base}/v2/upload",
            headers=_headers(api_key),
            data=audio_data,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"assemblyai upload HTTP {resp.status_code}: {resp.text[:200]}"
            )
        url = (resp.json() or {}).get("upload_url", "")
        if not url:
            raise RuntimeError("assemblyai upload: missing upload_url")
        return str(url)

    def _submit(self, audio_url: str, api_key: str, base: str) -> str:
        import requests

        payload: dict = {
            "audio_url": audio_url,
            "punctuate": True,
            "format_text": True,
        }
        if self.language_code:
            payload["language_code"] = self.language_code
        else:
            payload["language_detection"] = True
        resp = requests.post(
            f"{base}/v2/transcript",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"assemblyai submit HTTP {resp.status_code}: {resp.text[:200]}"
            )
        tid = (resp.json() or {}).get("id", "")
        if not tid:
            raise RuntimeError("assemblyai submit: missing transcript id")
        return str(tid)

    def _poll(self, transcript_id: str, api_key: str, base: str) -> dict:
        import requests

        url = f"{base}/v2/transcript/{transcript_id}"
        deadline = time.monotonic() + self.timeout_s
        while True:
            resp = requests.get(url, headers=_headers(api_key), timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"assemblyai poll HTTP {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json() or {}
            status = data.get("status")
            if status == "completed":
                return data
            if status == "error":
                raise RuntimeError(f"assemblyai error: {data.get('error', '')[:200]}")
            if time.monotonic() > deadline:
                raise TimeoutError("assemblyai polling timed out")
            time.sleep(self.poll_interval_s)

    def transcribe(
        self, audio_data: bytes, mime_type: str = "audio/ogg"
    ) -> AssemblyAIResult:
        """Transcribe raw bytes -> Arabic text. Raises on failure."""
        if not audio_data:
            raise ValueError("empty audio bytes")
        if len(audio_data) > MAX_AUDIO_BYTES:
            raise ValueError("audio too large for AssemblyAI upload path")
        api_key = _api_key(self._explicit_key)
        base = _base_url()
        log.info("assemblyai upload bytes=%d mime=%s", len(audio_data), mime_type)
        upload_url = self._upload(audio_data, api_key, base)
        tid = self._submit(upload_url, api_key, base)
        log.info("assemblyai submitted id=%s", tid[:8])
        data = self._poll(tid, api_key, base)
        text = str(data.get("text") or "").strip()
        log.info("assemblyai completed id=%s chars=%d", tid[:8], len(text))
        return AssemblyAIResult(
            text=text,
            transcript_id=tid,
            language_code=str(data.get("language_code") or self.language_code or ""),
            confidence=data.get("confidence"),
            audio_duration=data.get("audio_duration"),
        )

    def transcribe_simple(self, audio_data: bytes, mime_type: str = "audio/ogg") -> str:
        """Same as transcribe() but returns plain text ('' on any failure)."""
        try:
            return self.transcribe(audio_data, mime_type=mime_type).text
        except Exception as exc:  # noqa: BLE001 — STT must never break intake
            log.warning("assemblyai transcribe failed: %s", exc)
            return ""
