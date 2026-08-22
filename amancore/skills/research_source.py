"""Research sources (pluggable). No browser automation in production."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from ..errors import RoutingError


@dataclass
class RawResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "unknown"


class ResearchSource:
    def search(self, query: str, market: str, limit: int) -> list[RawResult]:
        raise NotImplementedError


class FixtureResearchSource(ResearchSource):
    """Deterministic source for tests/demos."""

    def __init__(self, results: list[RawResult] | None = None):
        self._results = results or []

    def search(self, query: str, market: str, limit: int) -> list[RawResult]:
        return self._results[:limit]


class HttpResearchSource(ResearchSource):
    """Calls a configured search endpoint (JSON). Not configured by default."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None):
        self.endpoint = endpoint
        self.api_key = api_key

    def search(self, query: str, market: str, limit: int) -> list[RawResult]:
        if not self.endpoint:
            raise RoutingError("web research source not configured (no endpoint)")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = requests.get(
            self.endpoint,
            params={"q": query, "market": market, "limit": limit},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            RawResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                source=item.get("source", "web"),
            )
            for item in data.get("results", [])
        ]


def build_source(source_config: dict | None) -> ResearchSource:
    source_config = source_config or {}
    if source_config.get("type") == "http":
        return HttpResearchSource(source_config.get("endpoint"), source_config.get("api_key_env"))
    return FixtureResearchSource()
