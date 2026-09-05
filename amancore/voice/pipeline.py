"""Voice -> text -> DeepSeek pipeline.

Step 1 (STT): AssemblyAI transcribes audio bytes -> Arabic text.
Step 2 (LLM): that text continues via DeepSeek-V4-Flash-Vision-Exp ONLY
  (model='deepseek-v4-flash-vision-exp', OpenAI-compatible chat).
  No regular deepseek-v4-flash is used anywhere (owner requirement).
  Pure function flow — the caller (coordinator / telegram console) then
  feeds the reply into the normal outbox path.

Secrets: ASSEMBLYAI_API_KEY + DEEPSEEK_API_KEY from env only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..log import get_logger
from .assemblyai import AssemblyAITranscriber

log = get_logger("voice.pipeline")

# Single DeepSeek model used everywhere (vision-exp only, never plain flash).
DEEPSEEK_VISION_MODEL_DEFAULT = "deepseek-v4-flash-vision-exp"
DEEPSEEK_BASE_URL_DEFAULT = "https://api.deepseek.com"

VOICE_REPLY_SYSTEM = (
    "أنت مساعد أمان كود (AmanCode). أجب باللغة العربية باختصار ودفء، "
    "خطوة واحدة فقط في كل رسالة، ولا تخترع أسعارًا."
)


def continue_with_deepseek(
    user_text: str,
    system: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    chat_model: str | None = None,
    timeout: int = 60,
) -> str:
    """Continue a transcribed voice text via DeepSeek-Vision-Exp. Raises on failure.

    Only model ever sent: deepseek-v4-flash-vision-exp. The `chat_model`
    arg is kept for back-compat but IGNORED when it is not vision-exp
    (owner requirement: never use plain deepseek-v4-flash).
    """
    import requests

    key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")
    base = (base_url or os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL_DEFAULT)).rstrip("/")
    requested = chat_model or os.environ.get("DEEPSEEK_VISION_MODEL", DEEPSEEK_VISION_MODEL_DEFAULT)
    if requested != DEEPSEEK_VISION_MODEL_DEFAULT:
        log.warning("ignoring non-vision model %r, forcing %s", requested, DEEPSEEK_VISION_MODEL_DEFAULT)
    model = DEEPSEEK_VISION_MODEL_DEFAULT
    messages = [
        {"role": "system", "content": system or VOICE_REPLY_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"deepseek vision-exp HTTP {resp.status_code}: {resp.text[:200]}")
    text = str(resp.json()["choices"][0]["message"]["content"] or "").strip()
    log.info("deepseek vision-exp continue ok chars=%d", len(text))
    return text


@dataclass
class VoicePipelineResult:
    transcript: str
    reply: str
    transcript_id: str = ""
    llm_model: str = ""


def transcribe_and_continue(
    audio_data: bytes,
    mime_type: str = "audio/ogg",
    system: str | None = None,
) -> VoicePipelineResult:
    """Full flow: AssemblyAI STT -> DeepSeek text reply.

    Raises RuntimeError with a clear message if STT or LLM is unconfigured;
    returns empty strings (never raises) only for empty audio input.
    """
    if not audio_data:
        return VoicePipelineResult(transcript="", reply="")
    stt = AssemblyAITranscriber()
    res = stt.transcribe(audio_data, mime_type=mime_type)
    if not res.text:
        raise RuntimeError("assemblyai returned empty transcript")
    reply = continue_with_deepseek(res.text, system=system)
    return VoicePipelineResult(
        transcript=res.text, reply=reply, transcript_id=res.transcript_id,
        llm_model=DEEPSEEK_VISION_MODEL_DEFAULT,
    )
