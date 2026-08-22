"""Content Agent — ideation, drafting, localization, repurposing.

Cannot publish externally, send messages, modify Business Brain, or invent
claims (all claims pass through the Claim Gate before approval).
"""

from __future__ import annotations

import json

from ..content.service import ContentService
from ..ids import new_id
from ..util import run_text
from .base import Agent


class ContentAgent(Agent):
    def __init__(
        self,
        brain_store,
        content_service: ContentService,
        approval_service,
        localization_skill,
        social_skill,
        **kw,
    ):
        super().__init__("content", brain_store, **kw)
        self.content_service = content_service
        self.approval = approval_service
        self.localization_skill = localization_skill
        self.social_skill = social_skill

    def draft(
        self,
        topic: str,
        market: str,
        language: str,
        content_type: str = "linkedin_post",
        angle: str = "",
        hook: str = "",
        cta: str = "Book a free digital checkup",
    ) -> str:
        body = self._draft_text(topic, market, language, content_type, angle, hook, cta)
        content_id = self.content_service.create(
            title=topic,
            topic=topic,
            market=market,
            language=language,
            content_type=content_type,
            platform=self._platform(content_type),
            angle=angle,
            hook=hook,
            body=body,
            cta=cta,
        )
        self._apply_approval(content_id, body)
        return content_id

    def localize(self, content_id: str, market: str, language: str, high_risk: bool = False) -> str:
        content = self.content_service.get(content_id)
        if content is None:
            raise ValueError(f"content {content_id} not found")
        localized = self.localization_skill.localize(
            content.get("body", ""), market, language, content.get("content_type", ""), high_risk
        )
        new_id_ = self.content_service.create(
            title=content.get("title", ""),
            topic=content.get("topic", ""),
            market=market,
            language=language,
            content_type=content.get("content_type", ""),
            platform=content.get("platform", ""),
            angle=content.get("angle", ""),
            hook=content.get("hook", ""),
            body=localized["text"],
            cta=content.get("cta", ""),
            source_research_ids=content.get("source_research_ids"),
        )
        self._apply_approval(new_id_, localized["text"])
        return new_id_

    def repurpose(self, content_id: str, cta: str = "") -> list[str]:
        content = self.content_service.get(content_id)
        if content is None:
            raise ValueError(f"content {content_id} not found")
        formats = self.social_skill.generate(
            topic=content.get("topic", ""),
            angle=content.get("angle", ""),
            hook=content.get("hook", ""),
            market=content.get("market", ""),
            language=content.get("language", ""),
            cta=cta or content.get("cta", ""),
        )
        created: list[str] = []
        for fmt, item in formats.items():
            cid = self.content_service.create(
                title=content.get("title", ""),
                topic=content.get("topic", ""),
                market=content.get("market", ""),
                language=content.get("language", ""),
                content_type=fmt,
                platform=item.get("platform", ""),
                angle=content.get("angle", ""),
                hook=item.get("hook", ""),
                body=item.get("body", ""),
                cta=item.get("cta", ""),
                source_research_ids=content.get("source_research_ids"),
            )
            self._apply_approval(cid, item.get("body", ""))
            created.append(cid)
        return created

    def _draft_text(self, topic, market, language, content_type, angle, hook, cta) -> str:
        prompt = _DRAFT_PROMPT.format(
            topic=topic, market=market, language=language,
            content_type=content_type, angle=angle, hook=hook, cta=cta,
        )
        text = run_text(self.router, "routine", prompt)
        if text:
            return text
        return f"{hook or angle}\n\n{topic} — {content_type} for the {market} market.\n\n{cta}"

    def _apply_approval(self, content_id: str, body: str) -> None:
        content = {"content_id": content_id, "title": self.content_service.get(content_id)["title"], "body": body}
        decision = self.approval.evaluate(content)
        self.content_service.update(
            content_id,
            status=decision["status"],
            claim_status=decision["claim_status"],
            risk_level=decision["risk_level"],
            approval_status="pending" if decision["needs_owner"] else decision["status"],
        )
        event = "content.approved" if decision["status"] == "approved" else (
            "content.rejected" if decision["status"] == "rejected" else "content.review"
        )
        self._emit(event, {"content_id": content_id, "decision": decision}, correlation_id=new_id())
        self._audit(event, "content", result=decision["status"])

    @staticmethod
    def _platform(content_type: str) -> str:
        return {
            "linkedin_post": "linkedin",
            "instagram_caption": "instagram",
            "carousel": "instagram",
            "reel_script": "instagram",
            "tiktok_script": "tiktok",
            "facebook_post": "facebook",
            "blog": "website",
        }.get(content_type, "")


_DRAFT_PROMPT = """Write a short, professional {content_type} for AmanCore in language={language}
targeting market={market}. Keep brand voice: professional, clear, outcome-focused.
Topic: {topic}
Angle: {angle}
Hook: {hook}
CTA: {cta}

Do NOT invent customers, revenue numbers, testimonials, or guarantees.
Return ONLY the post text.
"""
