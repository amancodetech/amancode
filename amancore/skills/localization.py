"""Localization skill — market-aware adaptation, not literal translation."""

from __future__ import annotations

from ..util import run_text


class LocalizationSkill:
    def __init__(self, router=None, brain_store=None):
        self.router = router
        self.brain_store = brain_store

    def localize(
        self,
        text: str,
        market: str,
        language: str,
        content_type: str = "",
        high_risk: bool = False,
    ) -> dict:
        """Return {language, market, text, notes}."""
        if not text.strip():
            return {"language": language, "market": market, "text": text, "notes": "empty"}
        if self.router is None:
            return {
                "language": language,
                "market": market,
                "text": text,
                "notes": "passthrough (no router configured)",
            }
        task_class = "reasoning" if high_risk else "routine"
        prompt = _LOCALIZE_PROMPT.format(
            text=text, market=market, language=language, content_type=content_type
        )
        localized = run_text(self.router, task_class, prompt, default=text)
        return {
            "language": language,
            "market": market,
            "text": localized,
            "notes": "localized",
        }


_LOCALIZE_PROMPT = """Localize this content for market={market} in language={language} (content_type={content_type}).
This is NOT literal translation:
- keep meaning, factual claims, CTA intent, and brand identity
- adapt vocabulary, tone, examples, cultural context, and commercial wording

Return ONLY the localized text, no commentary.

Text:
{text}
"""
