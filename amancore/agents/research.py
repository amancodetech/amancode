"""Research Agent — discover/enrich leads, competitors, and content topics.

Research only: it cannot send messages, publish content, negotiate, or modify
Business Brain.
"""

from __future__ import annotations

import json

from ..ids import new_id
from ..sales.fit import compute_fit
from .base import Agent


class ResearchAgent(Agent):
    def __init__(self, brain_store, crm, lead_skill, competitor_skill, content_skill, **kw):
        super().__init__("research", brain_store, crm=crm, **kw)
        self.lead_skill = lead_skill
        self.competitor_skill = competitor_skill
        self.content_skill = content_skill

    def discover_leads(self, query: str, market: str, limit: int = 10) -> dict:
        correlation_id = new_id()
        self._emit("research.started", {"query": query, "market": market}, correlation_id=correlation_id)
        try:
            results = self.lead_skill.discover(query, market, limit)
            summary = {"discovered": 0, "created": 0, "updated": 0, "rejected": 0, "duplicates": 0}
            for r in results:
                if not r.company_name and not r.website:
                    summary["rejected"] += 1
                    self._emit("lead.rejected", {"reason": "no company/website"}, correlation_id)
                    continue
                fit = compute_fit(self.brain, r.to_dict())
                provenance = json.dumps({
                    "source": r.source,
                    "source_url": r.source_url,
                    "retrieved_at": r.retrieved_at,
                    "research_method": r.research_method,
                    "confidence": r.confidence,
                }, ensure_ascii=False)
                existing = self.crm.find_lead(company=r.company_name or None, website=r.website or None)
                if existing:
                    summary["duplicates"] += 1
                    summary["updated"] += 1
                    lead = existing[0]
                    self.crm.update_lead(
                        lead["lead_id"],
                        industry=r.industry or lead.get("industry"),
                        country=r.country or lead.get("country"),
                        fit_signals=json.dumps(fit, ensure_ascii=False),
                        provenance=provenance,
                    )
                    self._emit("lead.enriched", {"lead_id": lead["lead_id"]}, correlation_id)
                    self._emit("lead.duplicate_detected", {"lead_id": lead["lead_id"]}, correlation_id)
                    self._save_research_result(r, fit, lead["lead_id"])
                    continue
                lead_id = self.crm.create_lead(
                    company=r.company_name,
                    website=r.website,
                    industry=r.industry,
                    country=r.country,
                    market=r.market,
                    provenance=provenance,
                    fit_signals=json.dumps(fit, ensure_ascii=False),
                    source_channel="research",
                    source_search_term=query,
                )
                summary["created"] += 1
                self._emit("lead.discovered", {"lead_id": lead_id}, correlation_id)
                self._save_research_result(r, fit, lead_id)
            summary["discovered"] = summary["created"] + summary["updated"]
            self._emit("research.completed", summary, correlation_id=correlation_id)
            self._audit("research.completed", "research", result=json.dumps(summary))
            return summary
        except Exception as exc:  # noqa: BLE001
            self._emit("research.failed", {"error": str(exc)}, correlation_id=correlation_id)
            self._audit("research.failed", "research", result=str(exc))
            raise

    def research_competitor(self, name: str, url: str = "", market: str = "") -> dict:
        result = self.competitor_skill.analyze(name, url, market)
        self._audit("research.competitor", "research", result=name)
        return result

    def research_content(self, topic: str, market: str, language: str) -> list[dict]:
        result = self.content_skill.discover(topic, market, language)
        self._audit("research.content", "research", result=topic)
        return result

    def _save_research_result(self, r, fit: dict, lead_id: str) -> None:
        self.crm.create_research_result(
            type="lead",
            company_name=r.company_name,
            website=r.website,
            industry=r.industry,
            country=r.country,
            market=r.market,
            confidence=r.confidence,
            source=r.source,
            source_url=r.source_url,
            research_method=r.research_method,
            retrieved_at=r.retrieved_at,
            fit_json=json.dumps(fit, ensure_ascii=False),
            lead_id=lead_id,
        )
