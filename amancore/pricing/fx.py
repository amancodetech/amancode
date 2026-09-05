"""FX — market resolution + USD-base conversion with per-correspondence freeze.

Pricing doctrine (owner-approved):
  - USD is the FIXED base. The engine always computes USD-magnitude figures
    (market price-level multipliers from pricing_policy still apply).
  - Arabic market (gcc) is priced in USD, no conversion.
  - Indonesian market (the DEFAULT market) is priced in IDR, converted from
    the USD base at the Brain-pinned daily USD_IDR rate.
  - Every priced correspondence (T1/T2 text, approval payload, snapshot)
    freezes the (rate, date) it used, so a later Brain rate update can never
    rewrite an issued price. T3 replays the STORED figures verbatim.

No live FX calls at runtime: the owner pins the daily rate in the Brain
(fx_rates.USD_IDR + USD_IDR_date). Deterministic, auditable, testable.
"""

from __future__ import annotations

BASE_CURRENCY = "USD"

# Safe fallback when the Brain carries no fx_rates (old versions / tests).
FALLBACK_USD_IDR = 17650
FALLBACK_FX_DATE = "2026-09-03"

# IDR display rounding: nearest 100k keeps ~$5.6 granularity, clean figures.
IDR_ROUND = 100_000


def get_usd_idr_rate(brain: dict | None) -> tuple[int, str]:
    """Return (USD_IDR rate, rate date) from the Brain, with safe fallback."""
    brain = brain or {}
    fx = (brain.get("fx_rates") or {}) if isinstance(brain, dict) else {}
    try:
        rate = int(fx.get("USD_IDR") or FALLBACK_USD_IDR)
    except (TypeError, ValueError):
        rate = FALLBACK_USD_IDR
    if rate <= 0:
        rate = FALLBACK_USD_IDR
    date = str(fx.get("USD_IDR_date") or FALLBACK_FX_DATE)
    return rate, date


def resolve_market(language: str | None = None,
                   lead: dict | None = None) -> tuple[str, str]:
    """Resolve (market, currency) — the SINGLE market authority.

    Rules (owner-approved):
      - Arabic language  -> gcc / USD (always dollars for the Arab market).
      - Anything else, including unknown/empty -> indonesia / IDR
        (Indonesian is the DEFAULT market).
      - An explicit lead market is honored ONLY for gcc/indonesia;
        other profile markets (malaysia/singapore) are out of the focused
        scope and fall back to the default (indonesia/IDR) for figures.
    """
    lang = (language or "").strip().lower()
    if lang.startswith("ar"):
        return "gcc", "USD"
    explicit = ((lead or {}).get("market") or "").strip().lower()
    if explicit == "gcc":
        return "gcc", "USD"
    return "indonesia", "IDR"


def usd_to_idr(usd_amount: float, rate: int) -> int:
    """Convert a USD figure to IDR, rounded to clean display granularity."""
    return int(round(float(usd_amount) * int(rate) / IDR_ROUND) * IDR_ROUND)


def format_idr(amount: int) -> str:
    """Indonesian formatting: Rp24.700.000 (dots, no decimals)."""
    return "Rp" + f"{int(amount):,}".replace(",", ".")


def format_usd(amount: float) -> str:
    """USD formatting matching the historical style: 1,500 USD."""
    if float(amount) == int(amount):
        return f"{int(amount):,} USD"
    return f"{float(amount):g} USD"
