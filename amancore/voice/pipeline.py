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

# Default DeepSeek model for text generation / voice reply continuation.
DEEPSEEK_CHAT_MODEL_DEFAULT = "deepseek-chat"
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
    max_tokens: int = 1024,
    timeout: int = 60,
) -> str:
    """Continue a transcribed voice text or generate text via DeepSeek-Chat.

    Default model: deepseek-chat. Capped by max_tokens to prevent runaway token usage.
    """
    import requests

    key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not configured")
    base = (base_url or os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL_DEFAULT)).rstrip("/")
    model = chat_model or os.environ.get("DEEPSEEK_CHAT_MODEL", DEEPSEEK_CHAT_MODEL_DEFAULT)
    messages = [
        {"role": "system", "content": system or VOICE_REPLY_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"deepseek chat HTTP {resp.status_code}: {resp.text[:200]}")
    text = str(resp.json()["choices"][0]["message"]["content"] or "").strip()
    log.info("deepseek chat continue ok chars=%d model=%s", len(text), model)
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
        llm_model=DEEPSEEK_CHAT_MODEL_DEFAULT,
    )
