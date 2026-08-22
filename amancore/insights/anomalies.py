"""Anomaly Detector — deterministic z-score based.

Anomaly + Materiality + Confidence = Actionable Insight.
A deviation alone is NOT a problem.
"""

from __future__ import annotations

import math
import statistics


def zscore(value: float, history: list[float], config: dict) -> float | None:
    """z-score of `value` vs history. None if history too small."""
    min_periods = int(config.get("min_periods", 3))
    if len(history) < min_periods:
        return None
    mean = statistics.mean(history)
    stdev = statistics.pstdev(history)
    if stdev == 0:
        return 0.0
    return (value - mean) / stdev


def is_anomaly(value: float, history: list[float], config: dict) -> tuple[bool, float | None]:
    """Returns (is_anomaly, z). Requires enough history."""
    z = zscore(value, history, config)
    if z is None:
        return False, None
    threshold = float(config.get("zscore_threshold", 2.0))
    return abs(z) >= threshold, z


def materialized_anomaly(
    *,
    metric: str,
    value: float,
    history: list[float],
    config: dict,
    monetary_impact: float | None = None,
    direction: str = "any",
) -> dict | None:
    """Combined check: anomaly + materiality => actionable anomaly dict (or None)."""
    flagged, z = is_anomaly(value, history, config)
    if not flagged:
        return None
    if direction == "high" and z < 0:
        return None
    if direction == "low" and z > 0:
        return None
    mean = statistics.mean(history) if history else 0.0
    deviation_pct = round((value - mean) / max(abs(mean), 1e-9), 4) if mean else 0.0
    return {
        "metric": metric,
        "value": value,
        "z_score": round(z, 3) if z is not None else None,
        "deviation_pct": deviation_pct,
        "history_mean": round(mean, 4),
        "monetary_impact": monetary_impact,
        "history": history,
    }
