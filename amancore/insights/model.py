"""Insight domain model — builders + validation (deterministic)."""

from __future__ import annotations

from ..ids import new_id, utcnow

CONFIDENCE = ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT_DATA")
SEVERITY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
INSIGHT_STATUS = ("new", "reviewed", "accepted", "rejected", "dismissed", "expired", "superseded")
RECOMMENDATION_TYPES = (
    "observe", "investigate", "optimize", "test",
    "change_policy", "change_offer", "change_pricing", "change_process",
    "capacity", "product_opportunity",
)
APPROVAL_REQUIRED_TYPES = {
    "change_policy", "change_offer", "change_pricing", "capacity",
    "product_opportunity",
}
RECOMMENDATION_STATUS = (
    "new", "under_review", "accepted", "rejected", "deferred",
    "implemented", "expired", "superseded",
)

CATEGORIES = {
    "acquisition", "sales", "pricing", "revenue", "margin", "offer",
    "market", "content", "support", "operations", "capacity", "customer",
    "recurring", "ai_cost", "risk", "product", "data_quality",
}


def confidence_from_samples(n: int, effect_strength: float, policy: dict) -> str:
    """Deterministic confidence model.

    n: sample size. effect_strength: 0..1 (how strong/clean the pattern is).
    policy: insight_policy config (minimum_samples, sample_high, sample_medium,
    confidence_threshold).
    """
    minimum = policy.get("minimum_samples", 3)
    high_n = policy.get("sample_high", 10)
    med_n = policy.get("sample_medium", 5)
    threshold = policy.get("confidence_threshold", 0.7)
    if n < minimum:
        return "INSUFFICIENT_DATA"
    if n >= high_n and effect_strength >= threshold:
        return "HIGH"
    if n >= med_n:
        return "MEDIUM" if effect_strength >= 0.4 else "LOW"
    return "LOW"


def severity_for(
    confidence: str,
    monetary_impact: float | None,
    is_risk: bool = False,
    is_critical: bool = False,
    policy: dict | None = None,
) -> str:
    """Severity = materiality + risk. Never HIGH from a tiny sample."""
    materiality = (policy or {}).get("materiality_threshold", 200)
    if is_critical:
        return "CRITICAL"
    if confidence == "INSUFFICIENT_DATA":
        return "LOW"
    impact = monetary_impact or 0.0
    if is_risk or impact >= materiality * 3:
        return "HIGH" if confidence in ("HIGH", "MEDIUM") else "MEDIUM"
    if impact >= materiality:
        return "MEDIUM"
    return "LOW"


def build_evidence(*, source: str, metric: str, value, baseline=None,
                   comparison: str = "unavailable", period: str = "",
                   sample_size: int = 0, caveats: str = "") -> dict:
    return {
        "source": source,
        "metric": metric,
        "value": value,
        "baseline": baseline,
        "comparison": comparison,
        "period": period,
        "sample_size": sample_size,
        "caveats": caveats,
    }


def new_insight(
    *,
    type_: str,
    category: str,
    title: str,
    summary: str,
    evidence: dict | list,
    confidence: str,
    severity: str,
    metrics: dict | None = None,
    period: str = "",
    segment: str = "",
    business_impact: str = "",
    fingerprint: str = "",
    related_entities: list | None = None,
    expires_at: str | None = None,
) -> dict:
    return {
        "insight_id": new_id(),
        "type": type_,
        "category": category,
        "title": title,
        "summary": summary,
        "evidence": evidence,
        "metrics": metrics or {},
        "period": period,
        "segment": segment,
        "confidence": confidence,
        "severity": severity,
        "business_impact": business_impact,
        "status": "new",
        "recommendation_id": None,
        "related_entities": related_entities or [],
        "fingerprint": fingerprint,
        "expires_at": expires_at,
        "superseded_by": None,
        "detected_at": utcnow(),
    }


def new_recommendation(
    *,
    insight_id: str,
    type_: str,
    title: str,
    problem: str,
    evidence_ids: list,
    proposed_action: str,
    alternatives: list,
    expected_benefit: str,
    expected_risk: str,
    dependencies: str,
    confidence: str,
    requires_owner_approval: bool,
    what_if_ignored: str = "",
    required_decision: str = "",
) -> dict:
    return {
        "recommendation_id": new_id(),
        "insight_id": insight_id,
        "type": type_,
        "title": title,
        "problem": problem,
        "evidence": {"evidence_ids": evidence_ids},
        "proposed_action": proposed_action,
        "alternatives": alternatives,
        "expected_benefit": expected_benefit,
        "expected_risk": expected_risk,
        "dependencies": dependencies,
        "confidence": confidence,
        "requires_owner_approval": requires_owner_approval,
        "what_if_ignored": what_if_ignored,
        "required_decision": required_decision,
        "status": "new",
        "decision": None,
        "decided_by": None,
        "decided_at": None,
        "approval_id": None,
        "brain_change_proposal_id": None,
    }
