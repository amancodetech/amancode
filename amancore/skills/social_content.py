"""Social content skill — turn one idea into platform-specific formats.

No publishing — only drafts per platform.
"""

from __future__ import annotations

from ..util import run_json

_PLATFORMS = {
    "linkedin_post": {"platform": "linkedin", "tone": "professional", "length": "long"},
    "instagram_caption": {"platform": "instagram", "tone": "engaging", "length": "short"},
    "carousel": {"platform": "instagram", "tone": "educational", "length": "slides"},
    "reel_script": {"platform": "instagram", "tone": "visual", "length": "30-60s"},
    "tiktok_script": {"platform": "tiktok", "tone": "energetic", "length": "30-60s"},
    "facebook_post": {"platform": "facebook", "tone": "conversational", "length": "medium"},
}


class SocialContentSkill:
    def __init__(self, router=None):
        self.router = router

    def generate(self, topic: str, angle: str, hook: str, market: str, language: str, cta: str = "") -> dict:
        """Return {format: {content_type, platform, body, hook, cta, tone, length}}."""
        if self.router is not None:
            data = run_json(
                self.router,
                "routine",
                _SOCIAL_PROMPT.format(
                    topic=topic, angle=angle, hook=hook, market=market, language=language, cta=cta
                ),
            )
            if isinstance(data, dict):
                out = {}
                for fmt, meta in _PLATFORMS.items():
                    item = data.get(fmt)
                    if isinstance(item, dict):
                        out[fmt] = {**meta, "content_type": fmt, **item}
                if out:
                    return out
        # deterministic fallback
        return {
            fmt: {
                "content_type": fmt,
                "platform": meta["platform"],
                "tone": meta["tone"],
                "length": meta["length"],
                "hook": hook,
                "body": f"{hook} — {angle} ({topic})",
                "cta": cta,
            }
            for fmt, meta in _PLATFORMS.items()
        }


_SOCIAL_PROMPT = """Create platform-specific versions of ONE idea. Return ONLY a JSON object with keys:
linkedin_post, instagram_caption, carousel, reel_script, tiktok_script, facebook_post.
Each value is an object: {hook, body, cta, tone, length}.

Adapt format/hook/length/CTA/tone per platform (not a literal copy).

Topic: {topic}
Angle: {angle}
Hook: {hook}
Market: {market}
Language: {language}
Base CTA: {cta}
"""
