"""Content research skill — discover pain points, intents, and content angles."""

from __future__ import annotations

from ..ids import utcnow
from ..util import run_json
from .research_source import ResearchSource


class ContentResearchSkill:
    def __init__(self, source: ResearchSource, router=None):
        self.source = source
        self.router = router

    def discover(self, topic: str, market: str, language: str, limit: int = 5) -> list[dict]:
        opportunities: list[dict] = []
        raw = self.source.search(topic, market, limit)
        if self.router is not None:
            data = run_json(
                self.router,
                "extraction",
                _CONTENT_PROMPT.format(topic=topic, market=market, language=language),
            )
            if isinstance(data, list):
                opportunities = [o for o in data if isinstance(o, dict)]
        if not opportunities:
            opportunities = [
                {
                    "topic": topic,
                    "audience": "",
                    "market": market,
                    "language": language,
                    "pain_point": "",
                    "search_intent": "",
                    "angle": "",
                    "hook": "",
                    "recommended_format": "linkedin_post",
                    "CTA": "Book a free digital checkup",
                    "sources": [r.url for r in raw if r.url],
                    "confidence": "low",
                }
            ]
        for o in opportunities:
            o.setdefault("market", market)
            o.setdefault("language", language)
            o.setdefault("sources", [r.url for r in raw if r.url])
            o.setdefault("confidence", "low")
        return opportunities


_CONTENT_PROMPT = """Generate 3 content opportunities as a JSON list. Each object:
topic, audience, market, language, pain_point, search_intent, angle, hook,
recommended_format (linkedin_post|instagram_caption|carousel|reel_script|tiktok_script|facebook_post|blog),
CTA, confidence (high|medium|low).

Topic: {topic}
Market: {market}
Language: {language}
"""
