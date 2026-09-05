"""Image understanding via DeepSeek-V4-Flash-Vision-Exp (text + image).

Official API: OpenAI-compatible Chat Completions with
model='deepseek-v4-flash-vision-exp'.
Supported formats: JPEG / PNG / GIF / WebP (detected from file BYTES,
never from extension or declared MIME).

Three transports exist upstream (base64 data-URL, public http(s) URL,
Files API file_id). This module implements the two stateless ones
(base64 + URL) — the correct default for WhatsApp/Telegram/FB/IG inbound
images which are one-shot and private. Files API (upload once, reuse via
file_id) is intentionally NOT used here to avoid retention lifecycle.

Limits enforced locally (mirror of official docs):
- single base64/URL image <= 32 MiB
- request body is bounded by caller (payload is one image + prompt)
- images are sent in `user` messages ONLY (system/assistant images = 400)
- detail='high' for anything with text (receipts, screenshots, charts)

Audio is explicitly OUT OF SCOPE: this model does not accept audio.
Voice notes stay on Gemini Multimodal Audio (amancore.voice.processor).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from ..log import get_logger

log = get_logger("vision.processor")

VISION_MODEL = "deepseek-v4-flash-vision-exp"
VISION_BASE_URL_DEFAULT = "https://api.deepseek.com"
MAX_IMAGE_BYTES = 32 * 1024 * 1024  # 32 MiB per image (base64/URL path)

# magic-byte signatures (content sniffing, not extension)
_MIME_BY_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # + b"WEBP" at offset 8, checked below
)

SUPPORTED_MIMES = ("image/jpeg", "image/png", "image/gif", "image/webp")

DEFAULT_PROMPT = (
    "صف هذه الصورة بدقة باللغة العربية، واقرأ أي نص ظاهر فيها حرفيًا، "
    "واذكر العناصر المهمة (أشخاص/منتجات/مستندات/أرقام) باختصار."
)


def detect_image_mime(data: bytes) -> str | None:
    """Detect JPEG/PNG/GIF/WebP from file bytes. Returns None if unsupported."""
    if not data:
        return None
    for magic, mime in _MIME_BY_MAGIC:
        if data.startswith(magic):
            if mime == "image/webp":
                # RIFF....WEBP
                if len(data) >= 12 and data[8:12] == b"WEBP":
                    return mime
                return None
            return mime
    return None


def build_vision_messages(
    *,
    prompt: str,
    image_b64: str | None = None,
    mime: str | None = None,
    image_url: str | None = None,
    detail: str = "high",
) -> list[dict]:
    """Build OpenAI-compatible user message with text + one image.

    Exactly one of (image_b64+mime) or image_url must be given.
    Images always go in a `user` message (API rejects system images).
    """
    if bool(image_b64) == bool(image_url):
        raise ValueError("provide exactly one of image_b64 or image_url")
    if image_b64 is not None:
        if mime not in SUPPORTED_MIMES:
            raise ValueError(f"unsupported mime for vision: {mime!r}")
        url = f"data:{mime};base64,{image_b64}"
    else:
        url = str(image_url or "")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("image_url must be a public http(s) URL")
        if len(url) > 8192:
            raise ValueError("image_url exceeds 8192 characters")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or DEFAULT_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": url, "detail": detail},
                },
            ],
        }
    ]


@dataclass
class VisionResult:
    text: str
    model: str = VISION_MODEL
    provider: str = "deepseek_vision"
    mime: str = ""
    bytes: int = 0


class ImageUnderstandingService:
    """Text+image understanding via DeepSeek Vision, Gemini fallback.

    Usage:
        svc = ImageUnderstandingService()
        res = svc.describe(image_bytes, prompt="...")
        res = svc.describe_url("https://...", prompt="...")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL", VISION_BASE_URL_DEFAULT)
        ).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_VISION_MODEL", VISION_MODEL)

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post_chat(self, messages: list[dict], timeout: int = 60) -> str:
        import requests

        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages}
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(
                f"deepseek vision HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        return str(data["choices"][0]["message"]["content"] or "")

    def _gemini_fallback(
        self, image_bytes: bytes, mime: str, prompt: str
    ) -> str | None:
        """Best-effort Gemini image fallback (multimodal secondary)."""
        try:
            from google import genai
            from google.genai import types

            api_key = os.environ.get("GEMINI_API_KEY", "")
            if not api_key:
                return None
            client = genai.Client(api_key=api_key)
            model_id = os.environ.get("AMANCODE_MODEL_DEFAULT", "gemini-2.5-flash")
            part = types.Part.from_bytes(data=image_bytes, mime_type=mime)
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt), part],
                    )
                ],
            )
            return (response.text or "").strip() or None
        except Exception as exc:  # noqa: BLE001 — fallback is best-effort
            log.warning("gemini vision fallback failed: %s", exc)
            return None

    def describe(
        self,
        image_bytes: bytes,
        prompt: str | None = None,
        detail: str = "high",
    ) -> VisionResult:
        """Describe raw image bytes. Validates format + 32 MiB cap."""
        if not image_bytes:
            raise ValueError("empty image bytes")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"image too large: {len(image_bytes)} bytes > 32 MiB cap "
                "(use Files API path for up to 64 MiB)"
            )
        mime = detect_image_mime(image_bytes)
        if mime is None:
            raise ValueError(
                "unsupported image format: only JPEG/PNG/GIF/WebP "
                "(detected from file content)"
            )
        text_prompt = prompt or DEFAULT_PROMPT
        b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = build_vision_messages(
            prompt=text_prompt, image_b64=b64, mime=mime, detail=detail
        )
        try:
            text = self._post_chat(messages).strip()
            log.info("vision.describe ok model=%s mime=%s bytes=%d", self.model, mime, len(image_bytes))
            return VisionResult(text=text, model=self.model, mime=mime, bytes=len(image_bytes))
        except Exception as exc:
            log.warning("deepseek vision failed (%s), trying gemini fallback", exc)
            fb = self._gemini_fallback(image_bytes, mime, text_prompt)
            if fb:
                return VisionResult(
                    text=fb, model="gemini-fallback", provider="gemini",
                    mime=mime, bytes=len(image_bytes),
                )
            raise

    def describe_url(self, url: str, prompt: str | None = None) -> VisionResult:
        """Describe an already-public http(s) image URL (no download here)."""
        text_prompt = prompt or DEFAULT_PROMPT
        messages = build_vision_messages(prompt=text_prompt, image_url=url)
        text = self._post_chat(messages).strip()
        return VisionResult(text=text, model=self.model, mime="url", bytes=0)

    def describe_file(self, path: str | Path, prompt: str | None = None) -> VisionResult:
        p = Path(path)
        return self.describe(p.read_bytes(), prompt=prompt)
