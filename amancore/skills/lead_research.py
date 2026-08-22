"""Lead research skill: discover + normalize potential companies for the ICP."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse
from typing import Any

from ..ids import utcnow
from ..util import run_json
from .research_source import RawResult, ResearchSource

CONFIDENCE_SOURCE_MAP = {
    "official": "high",
    "verified": "high",
    "directory": "medium",
    "third_party": "medium",
    "inference": "low",
}


@dataclass
class ResearchResult:
    company_name: str = ""
    website: str = ""
    industry: str = ""
    country: str = ""
    city: str = ""
    market: str = ""
    public_contact: dict = field(default_factory=dict)
    social_profiles: dict = field(default_factory=dict)
    digital_presence_signals: dict = field(default_factory=dict)
    likely_needs: list = field(default_factory=list)
    service_fit: str = ""
    confidence: str = "low"
    source: str = ""
    source_url: str = ""
    research_method: str = ""
    retrieved_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def confidence_from_source(source: str) -> str:
    return CONFIDENCE_SOURCE_MAP.get((source or "").lower(), "low")


class LeadResearchSkill:
    def __init__(self, source: ResearchSource, router=None):
        self.source = source
        self.router = router

    def discover(self, query: str, market: str, limit: int = 10) -> list[ResearchResult]:
        raw_results = self.source.search(query, market, limit)
        out: list[ResearchResult] = []
        for raw in raw_results:
            result = self._extract(raw, market)
            if result is not None:
                out.append(result)
        return out

    def _extract(self, raw: RawResult, market: str) -> ResearchResult:
        domain = _domain(raw.url)
        # prefer LLM extraction when a router is available and there is data
        if self.router is not None and (raw.url or raw.title):
            data = run_json(
                self.router,
                "extraction",
                _EXTRACT_PROMPT.format(
                    title=raw.title, url=raw.url, snippet=raw.snippet, market=market
                ),
            )
            if isinstance(data, dict):
                return self._build(data, raw, market)
        # deterministic fallback (may be empty → agent rejects it)
        return ResearchResult(
            company_name=raw.title,
            website=domain,
            market=market,
            confidence=confidence_from_source(raw.source),
            source=raw.source,
            source_url=raw.url,
            research_method="fixture" if raw.source == "fixture" else "web",
            retrieved_at=utcnow(),
        )

    def _build(self, data: dict, raw: RawResult, market: str) -> ResearchResult:
        return ResearchResult(
            company_name=data.get("company_name") or raw.title,
            website=data.get("website") or _domain(raw.url),
            industry=data.get("industry", ""),
            country=data.get("country", ""),
            city=data.get("city", ""),
            market=data.get("market") or market,
            public_contact=data.get("public_contact") or {},
            social_profiles=data.get("social_profiles") or {},
            digital_presence_signals=data.get("digital_presence_signals") or {},
            likely_needs=data.get("likely_needs") or [],
            service_fit=data.get("service_fit", ""),
            confidence=data.get("confidence") or confidence_from_source(raw.source),
            source=data.get("source") or raw.source,
            source_url=data.get("source_url") or raw.url,
            research_method=data.get("research_method") or "web",
            retrieved_at=utcnow(),
        )


def _domain(url: str) -> str:
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return urlparse(url).netloc.lower().lstrip("www.")


_EXTRACT_PROMPT = """Extract structured company data from this research result as JSON.
Return ONLY valid JSON with these keys (empty string/missing when unknown):
company_name, website, industry, country, city, market, public_contact (object),
social_profiles (object), digital_presence_signals (object), likely_needs (list),
service_fit, confidence (high|medium|low), source, source_url, research_method.

Title: {title}
URL: {url}
Snippet: {snippet}
Market: {market}
"""
