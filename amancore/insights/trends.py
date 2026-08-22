"""Trend Detector — deterministic. No trend without enough data."""

from __future__ import annotations

import statistics

RISING = "rising"
FALLING = "falling"
STABLE = "stable"
VOLATILE = "volatile"
EMERGING = "emerging"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _linreg(values: list[float]) -> tuple[float, float]:
    """Least-squares slope + mean."""
    n = len(values)
    xs = list(range(n))
    mx = (n - 1) / 2
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0.0
    return slope, my


def detect(series: list[float], config: dict) -> tuple[str | None, str]:
    """Return (trend_label, confidence) or (None, INSUFFICIENT_DATA).

    Rules (config-driven, no arbitrary thresholds in code):
      - fewer than minimum_periods observations => no trend
      - direction from least-squares slope relative to the mean
      - high volatility with no direction => volatile
      - emerging: first half ~zero, second half nonzero
    """
    min_periods = int(config.get("minimum_periods", 2))
    change = float(config.get("change_threshold", 0.15))
    if len(series) < min_periods:
        return None, "INSUFFICIENT_DATA"
    clean = [float(v) for v in series]
    if all(v == 0 for v in clean):
        return STABLE, "HIGH"
    half = max(1, len(clean) // 2)
    first = _mean(clean[:half])
    second = _mean(clean[half:])
    # emerging: was ~zero, now growing
    if first < 1e-9 and second > 0:
        return EMERGING, "MEDIUM"
    slope, mean = _linreg(clean)
    rel = slope / max(abs(mean), 1e-9)
    threshold = change / 2
    # R² = fraction of variance explained by the linear trend
    var_x = sum((x - (len(clean) - 1) / 2) ** 2 for x in range(len(clean))) / len(clean)
    var_y = statistics.pstdev(clean) ** 2 if len(clean) > 1 else 0.0
    r2 = (slope ** 2 * var_x) / var_y if var_y > 0 else 0.0
    if rel >= threshold and r2 >= 0.4:
        strong = abs((clean[-1] - clean[0]) / max(clean[0], 1e-9)) >= 2 * change
        return RISING, "HIGH" if strong else "MEDIUM"
    if rel <= -threshold and r2 >= 0.4:
        strong = abs((clean[-1] - clean[0]) / max(clean[0], 1e-9)) >= 2 * change
        return FALLING, "HIGH" if strong else "MEDIUM"
    # direction not consistent (low R²) or too small: volatility is the signal
    volatility = statistics.pstdev(clean) / max(mean, 1e-9)
    if volatility > change * 2:
        return VOLATILE, "MEDIUM"
    return STABLE, "HIGH"


def classify_series(series: list[float], config: dict) -> dict:
    """Convenience: series -> {'trend': label|None, 'confidence': str,
    'change_pct': float|None, 'min':, 'max':, 'latest':}."""
    if not series:
        return {"trend": None, "confidence": "INSUFFICIENT_DATA", "change_pct": None,
                "min": None, "max": None, "latest": None}
    label, conf = detect(series, config)
    clean = [float(v) for v in series]
    half = max(1, len(clean) // 2)
    first = _mean(clean[:half])
    second = _mean(clean[half:])
    pct = round((second - first) / max(first, 1e-9), 4) if first or second else 0.0
    return {
        "trend": label,
        "confidence": conf,
        "change_pct": pct,
        "min": min(clean),
        "max": max(clean),
        "latest": clean[-1],
    }
