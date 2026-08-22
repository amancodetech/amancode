"""Competitor research skill — public data only, never fabricate claims."""

from __future__ import annotations

from ..ids import utcnow
from ..util import run_json
from .research_source import ResearchSource

_NOT_PUBLIC = "not_publicly_available"


class CompetitorResearchSkill:
    def __init__(self, source: ResearchSource, router=None):
        self.source = source
        self.router = router

    def analyze(self, name: str, url: str = "", market: str = "") -> dict:
        base = {
            "name": name,
            "website": url,
            "market": market,
            "services": [],
            "positioning": "",
            "offers": [],
            "pricing_visible": _NOT_PUBLIC,
            "content_strategy": "",
            "channels": [],
            "strengths": [],
            "weaknesses": [],
            "differentiation": "",
            "sources": [],
            "confidence": "low",
            "retrieved_at": utcnow(),
        }
        raw = self.source.search(name or url, market, limit=1)
        if raw:
            base["sources"] = [r.url for r in raw if r.url]
        if self.router is not None:
            data = run_json(
                self.router,
                "extraction",
                _COMPETITOR_PROMPT.format(name=name, url=url, market=market),
            )
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items() if k in base})
        # enforce no-fabrication rule for unknown pricing
        if base.get("pricing_visible") in (None, ""):
            base["pricing_visible"] = _NOT_PUBLIC
        return base


_COMPETITOR_PROMPT = """Analyze this competitor from public information only. Return ONLY JSON with:
name, website, market, services (list), positioning, offers (list),
pricing_visible (use exactly "not_publicly_available" if not public),
content_strategy, channels (list), strengths (list), weaknesses (list),
differentiation, sources (list), confidence (high|medium|low).

Do NOT invent prices, clients, revenue, or market share.

Competitor name: {name}
URL: {url}
Market: {market}
"""
