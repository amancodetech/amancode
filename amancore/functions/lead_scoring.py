"""Lead Scoring — deterministic function. No final-price authority."""

from __future__ import annotations

WEIGHTS = {
    "budget": 20,
    "need_urgency": 20,
    "authority": 15,
    "fit": 15,
    "business_value": 15,
    "project_clarity": 10,
    "engagement": 5,
}

HOT = "hot"
QUALIFIED = "qualified"
NURTURE = "nurture"


def category(score: int) -> str:
    if score >= 70:
        return HOT
    if score >= 40:
        return QUALIFIED
    return NURTURE


def score(qualification: dict, weights: dict | None = None) -> dict:
    weights = weights or WEIGHTS
    factor_scores: dict[str, int] = {}
    reasons: dict[str, str] = {}
    missing: list[str] = []
    known = 0

    # budget
    if qualification.get("budget"):
        factor_scores["budget"] = 4
        reasons["budget"] = "budget stated"
        known += 1
    else:
        factor_scores["budget"] = 0
        missing.append("budget")

    # need / urgency
    need = qualification.get("need")
    urgency = qualification.get("urgency")
    if need and urgency:
        factor_scores["need_urgency"] = 5
        reasons["need_urgency"] = "clear need + urgency"
        known += 1
    elif need:
        factor_scores["need_urgency"] = 3
        reasons["need_urgency"] = "need stated"
        known += 1
    else:
        factor_scores["need_urgency"] = 0
        missing.append("need_urgency")

    # authority
    authority = (qualification.get("authority") or "").lower()
    if authority:
        factor_scores["authority"] = 5 if any(k in authority for k in ("owner", "founder", "المالك", "صاحب", "decision")) else 3
        reasons["authority"] = "authority identified"
        known += 1
    else:
        factor_scores["authority"] = 0
        missing.append("authority")

    # fit
    overall = (qualification.get("fit") or {}).get("overall_fit", "")
    fit_score = {"high": 5, "medium": 3, "low": 1}.get(overall, 0)
    factor_scores["fit"] = fit_score
    if fit_score:
        reasons["fit"] = f"ICP fit {overall}"
        known += 1
    else:
        missing.append("fit")

    # business value
    if qualification.get("outcome"):
        factor_scores["business_value"] = 4
        reasons["business_value"] = "outcome stated"
        known += 1
    else:
        factor_scores["business_value"] = 0
        missing.append("business_value")

    # project clarity
    clarity = qualification.get("clarity", "low")
    clarity_score = {"high": 5, "medium": 3, "low": 1}.get(clarity, 1)
    factor_scores["project_clarity"] = clarity_score
    reasons["project_clarity"] = f"clarity {clarity}"
    known += 1

    # engagement
    engagement = int(qualification.get("engagement") or 0)
    factor_scores["engagement"] = min(engagement, 5)
    reasons["engagement"] = f"engagement {engagement}/5"
    known += 1 if engagement else 0

    total = round(sum(factor_scores[k] / 5 * weights[k] for k in weights if k in factor_scores))
    return {
        "score": total,
        "category": category(total),
        "factor_scores": factor_scores,
        "reasons": reasons,
        "missing_information": missing,
        "confidence": round(known / len(weights), 2),
    }
