"""Recommendation Engine — deterministic templates bound to evidence.

Rules:
  - Every recommendation carries evidence_ids (no hallucination rule).
  - INSUFFICIENT_DATA confidence => observe-only, never executive.
  - change_policy / change_offer / change_pricing / capacity => OWNER APPROVAL REQUIRED.
  - No free-form AI output becomes a business action: LLM interpretation is
    used only to enrich the explanation, never the decision fields.
"""

from __future__ import annotations

from .model import (
    APPROVAL_REQUIRED_TYPES,
    new_recommendation,
)

_INSUFFICIENT_REPLY = "Insufficient data — no executive recommendation. Collect more observations first."


class RecommendationEngine:
    def generate(self, insight: dict) -> dict:
        conf = insight.get("confidence", "INSUFFICIENT_DATA")
        if conf == "INSUFFICIENT_DATA":
            return self._observe(insight, _INSUFFICIENT_REPLY)
        kind = insight.get("type")
        handler = {
            "trend": self._trend,
            "anomaly": self._anomaly,
            "margin": self._margin,
            "pricing": self._pricing,
            "offer": self._offer,
            "sales_funnel": self._sales_funnel,
            "content": self._content,
            "support_recurrence": self._support_recurrence,
            "ai_cost": self._ai_cost,
            "capacity": self._capacity,
            "market": self._market,
            "saas_candidate": self._saas,
            "data_quality": self._data_quality,
            "opportunity": self._opportunity,
        }.get(kind, self._observe)
        return handler(insight)

    # ---- builders -------------------------------------------------------
    def _base(self, insight: dict, type_: str, title: str, problem: str,
              action: str, benefit: str, risk: str, alternatives: list,
              deps: str = "", what_if_ignored: str = "", decision: str = "") -> dict:
        return new_recommendation(
            insight_id=insight["insight_id"],
            type_=type_,
            title=title,
            problem=problem,
            evidence_ids=[insight["insight_id"]] + (insight.get("evidence_ids") or []),
            proposed_action=action,
            alternatives=alternatives,
            expected_benefit=benefit,
            expected_risk=risk,
            dependencies=deps,
            confidence=insight.get("confidence", "LOW"),
            requires_owner_approval=type_ in APPROVAL_REQUIRED_TYPES,
            what_if_ignored=what_if_ignored,
            required_decision=decision,
        )

    def _observe(self, insight: dict, note: str = "") -> dict:
        return self._base(
            insight, "observe",
            title=f"Observe: {insight.get('title', '')}",
            problem=insight.get("summary", ""),
            action=note or "Continue monitoring.",
            benefit="Better baseline before any change.",
            risk="None.",
            alternatives=["Wait for more data", "Investigate manually"],
            what_if_ignored="The situation continues; no action taken.",
            decision="No decision required.",
        )

    def _trend(self, insight: dict) -> dict:
        trend = (insight.get("metrics") or {}).get("trend", "")
        if trend in ("rising", "emerging"):
            return self._base(
                insight, "observe",
                title=f"Monitor rising {insight.get('segment') or insight.get('category')}",
                problem=insight["summary"],
                action="Maintain/increase focus on the rising area; ensure capacity exists.",
                benefit="Capture growth while it is observable.",
                risk="Over-investment if the trend reverses.",
                alternatives=["Hold steady", "Diversify"],
                what_if_ignored="Opportunity may be missed.",
                decision="Review in next weekly brief.",
            )
        if trend == "falling":
            return self._base(
                insight, "investigate",
                title=f"Investigate falling {insight.get('segment') or insight.get('category')}",
                problem=insight["summary"],
                action="Investigate likely causes before changing anything.",
                benefit="Avoid acting on noise.",
                risk="Inaction may extend the decline.",
                alternatives=["Investigate", "Adjust intake/pipeline"],
                what_if_ignored="Decline may continue unnoticed.",
                decision="Owner: approve investigation or accept observation.",
            )
        return self._observe(insight)

    def _anomaly(self, insight: dict) -> dict:
        return self._base(
            insight, "investigate",
            title=f"Anomaly: {insight.get('title', '')}",
            problem=insight["summary"],
            action="Investigate the anomaly before any policy reaction.",
            benefit="Confirms whether the deviation is real or a data artifact.",
            risk="Ignoring a real anomaly could hide a problem.",
            alternatives=["Verify data", "Investigate root cause"],
            what_if_ignored="Anomaly may persist.",
            decision="Owner: acknowledge or investigate.",
        )

    def _margin(self, insight: dict) -> dict:
        seg = insight.get("segment") or "service"
        return self._base(
            insight, "change_pricing",
            title=f"Review pricing policy for {seg}",
            problem=insight["summary"],
            action="Review the pricing policy for this segment (cost/markup/minimum) before any change.",
            benefit="Protects margin without arbitrary repricing.",
            risk="Pricing changes affect win rate; requires owner decision.",
            alternatives=["Keep pricing, monitor", "Review cost drivers", "Review scope"],
            deps="Approved pricing snapshot data",
            what_if_ignored="Margin compression may persist.",
            decision="Owner: approve pricing policy review.",
        )

    def _pricing(self, insight: dict) -> dict:
        return self._base(
            insight, "change_pricing",
            title=f"Pricing/offer review: {insight.get('segment', '')}",
            problem=insight["summary"],
            action="Review the offer/pricing configuration for the affected area.",
            benefit="Aligns offers with observed demand.",
            risk="Offer changes can shift conversion; owner decision required.",
            alternatives=["Keep as-is", "Test alternative offer"],
            what_if_ignored="Frequent objections continue.",
            decision="Owner: approve offer/pricing review.",
        )

    def _offer(self, insight: dict) -> dict:
        return self._base(
            insight, "change_offer",
            title=f"Offer review: {insight.get('segment', '')}",
            problem=insight["summary"],
            action="Review the offer structure (entry → core) for the affected service.",
            benefit="Better fit with observed demand.",
            risk="Offer changes require owner approval.",
            alternatives=["Adjust scope descriptions", "Keep current offers"],
            what_if_ignored="Offer mismatch persists.",
            decision="Owner: approve offer review.",
        )

    def _sales_funnel(self, insight: dict) -> dict:
        return self._base(
            insight, "optimize",
            title="Optimize sales funnel conversion",
            problem=insight["summary"],
            action="Focus on the weakest funnel conversion stage.",
            benefit="Higher close rate without price changes.",
            risk="Process changes need monitoring.",
            alternatives=["Investigate stage", "Adjust qualification"],
            what_if_ignored="Funnel leakage continues.",
            decision="Owner: acknowledge or direct investigation.",
        )

    def _content(self, insight: dict) -> dict:
        return self._base(
            insight, "optimize",
            title="Content optimization opportunity",
            problem=insight["summary"],
            action="Increase production of the content type/topic that converts.",
            benefit="More qualified leads from proven content.",
            risk="Single-topic concentration risk.",
            alternatives=["Diversify topics", "Test variations"],
            what_if_ignored="Proven content remains under-produced.",
            decision="Owner: approve content focus shift.",
        )

    def _support_recurrence(self, insight: dict) -> dict:
        return self._base(
            insight, "change_process",
            title="Recurring support issue",
            problem=insight["summary"],
            action="Address the recurring issue (process fix or product improvement).",
            benefit="Lower support load and higher satisfaction.",
            risk="Process changes need owner sign-off.",
            alternatives=["Document workaround", "Improve onboarding"],
            what_if_ignored="Support load keeps growing.",
            decision="Owner: approve process improvement.",
        )

    def _ai_cost(self, insight: dict) -> dict:
        return self._base(
            insight, "optimize",
            title="AI cost optimization",
            problem=insight["summary"],
            action="Review model routing: use Flash for routine work where safe.",
            benefit="Lower AI cost without quality loss.",
            risk="Do NOT downgrade high-risk tasks purely to save cost.",
            alternatives=["Keep routing", "Tune per-task routing"],
            what_if_ignored="Cost continues to grow.",
            decision="Owner: approve routing review.",
        )

    def _capacity(self, insight: dict) -> dict:
        return self._base(
            insight, "capacity",
            title="Capacity bottleneck",
            problem=insight["summary"],
            action="Capacity expansion should be considered (founder time/scope).",
            benefit="Protects delivery quality and margins.",
            risk="Expansion has cost; owner decision required.",
            alternatives=["Limit intake", "Raise scope bar", "Outsource selectively"],
            what_if_ignored="Delivery delays and support load grow.",
            decision="Owner: approve capacity plan.",
        )

    def _market(self, insight: dict) -> dict:
        return self._base(
            insight, "change_policy",
            title=f"Market opportunity review: {insight.get('segment', '')}",
            problem=insight["summary"],
            action="Review market focus — do NOT change primary/secondary markets automatically.",
            benefit="Evidence-based market allocation.",
            risk="Market shifts are strategic; owner decision required.",
            alternatives=["Keep current markets", "Pilot the opportunity"],
            what_if_ignored="Opportunity may go unaddressed.",
            decision="Owner: approve market review.",
        )

    def _saas(self, insight: dict) -> dict:
        return self._base(
            insight, "product_opportunity",
            title="Product/SaaS candidate detected",
            problem=insight["summary"],
            action="Evaluate the repeated problem as a potential product — do NOT build SaaS automatically.",
            benefit="Future recurring revenue.",
            risk="Product development is a major investment; owner decision required.",
            alternatives=["Document candidate", "Survey customers", "Ignore for now"],
            what_if_ignored="The opportunity remains unquantified.",
            decision="Owner: decide whether to pursue.",
        )

    def _data_quality(self, insight: dict) -> dict:
        return self._base(
            insight, "investigate",
            title="Data quality issue",
            problem=insight["summary"],
            action="Fix the underlying data entry/pipeline issue (no automatic edits).",
            benefit="Trustworthy analytics.",
            risk="None.",
            alternatives=["Document issue", "Fix intake"],
            what_if_ignored="Insights stay unreliable.",
            decision="Owner: acknowledge.",
        )

    def _opportunity(self, insight: dict) -> dict:
        return self._base(
            insight, "optimize",
            title="Opportunity follow-up",
            problem=insight["summary"],
            action="Prioritize follow-up on the detected opportunities.",
            benefit="Faster conversion of qualified pipeline.",
            risk="None.",
            alternatives=["Auto-followup", "Manual outreach"],
            what_if_ignored="Hot pipeline goes cold.",
            decision="Owner: acknowledge.",
        )
