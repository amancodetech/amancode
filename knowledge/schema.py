"""Knowledge Layer — record schema.

The Business Brain remains the single authoritative source of company truth,
pricing, claims, policies and approvals. This ``knowledge/`` layer holds only
EXTERNAL domain knowledge (industry context, standards, consultative method)
as versioned, provenance-bearing records. It has NO pricing, claims, approval,
compliance or company-truth authority.

Ownership of fields (anti-duplication rule):
    * The Brain owns  aliases, goals, typical_sections, features, conversion,
      trust_needs, objections, relevant_services, cross_sell,
      resources_for_followup.
    * A knowledge pack owns only the NEW fields added in the approved design:
      common_processes, common_pain_points, decision_roles, digital_maturity,
      typical_integrations, isic_refs, and provenance/version metadata.
A pack references its Brain profile by ``brain_profile_id`` and never re-states
Brain-owned fields.

statement_kind in this layer is RESTRICTED to RECOMMENDATION | METHOD.
FACT / AMANCODE_FACT / PRICING_REF are forbidden here — they belong only to the
Business Brain / PricingEngine.
"""

from __future__ import annotations

import re

# ---- allowed values --------------------------------------------------------
STATEMENT_KINDS = ("RECOMMENDATION", "METHOD")
AUTHORITY_LEVELS = ("official_standard", "official_statistics",
                    "methodology", "learned")
CONFIDENCE_LEVELS = ("high", "medium", "low")
DIGITAL_MATURITY = ("low", "medium", "high")

# ---- record field requirements ---------------------------------------------
REQUIRED_RECORD_FIELDS = (
    "id", "type", "statement_kind", "subject", "statement", "source",
    "authority", "confidence",
)
SOURCE_REQUIRED_FIELDS = (
    "name", "organization", "url", "version", "authority", "confidence",
    "extraction_date", "last_verified", "license",
)
# interaction_rule records reuse this shape (design §6).
REQUIRED_RULE_FIELDS = (
    "id", "type", "trigger", "rule", "allowed_use", "prohibited_use",
    "statement_kind", "source", "version",
)

# ---- industry pack fields (the ONLY extension fields this layer may carry) -
INDUSTRY_EXTENSION_FIELDS = (
    "common_processes", "common_pain_points", "decision_roles",
    "digital_maturity", "typical_integrations", "isic_refs",
)
REQUIRED_PACK_FIELDS = (
    "id", "brain_profile_id", "version", "last_verified", "sources",
) + INDUSTRY_EXTENSION_FIELDS


def normalize(v: str) -> str:
    return (v or "").strip().upper().replace(" ", "_")


def record_errors(record: dict, *, rule: bool = False) -> list[str]:
    """Return a list of human-readable validation errors for one record."""
    errs: list[str] = []
    required = REQUIRED_RULE_FIELDS if rule else REQUIRED_RECORD_FIELDS
    for field in required:
        if field not in record:
            errs.append(f"missing field: {field}")
    kind = record.get("statement_kind")
    if kind and normalize(kind) not in STATEMENT_KINDS:
        errs.append(f"invalid statement_kind: {kind!r} (only "
                    f"{'/'.join(STATEMENT_KINDS)})")
    auth = record.get("authority")
    if auth and normalize(auth) not in AUTHORITY_LEVELS:
        errs.append(f"invalid authority: {auth!r}")
    conf = record.get("confidence")
    if conf and normalize(conf) not in CONFIDENCE_LEVELS:
        errs.append(f"invalid confidence: {conf!r}")
    src = record.get("source")
    if not isinstance(src, dict):
        errs.append("source must be a dict (name/organization/url/version/"
                    "authority/confidence/extraction_date/last_verified/license)")
    else:
        authority = normalize(src.get("authority") or "")
        for field in SOURCE_REQUIRED_FIELDS:
            if field not in src:
                errs.append(f"source missing field: {field}")
                continue
            val = src[field]
            # url is optional-empty for methodology sources (may lack a
            # stable URL); non-empty required for official standards/statistics.
            if field == "url" and val in (None, "") and \
                    authority == "METHODOLOGY":
                continue
            if val in (None, ""):
                errs.append(f"source field empty: {field}")
    return errs


def pack_errors(pack: dict) -> list[str]:
    """Validate one industry knowledge pack (extension) record."""
    errs: list[str] = []
    for field in REQUIRED_PACK_FIELDS:
        if field not in pack:
            errs.append(f"pack missing field: {field}")
    if "id" in pack and "brain_profile_id" in pack \
            and pack["id"] != pack["brain_profile_id"]:
        errs.append(f"pack id {pack['id']!r} != brain_profile_id "
                    f"{pack['brain_profile_id']!r} (must reference the Brain "
                    "profile it extends)")
    # Brain-owned fields are forbidden here — anti-duplication rule.
    brain_owned = ("aliases", "goals", "typical_sections", "features",
                   "conversion", "trust_needs", "objections",
                   "relevant_services", "cross_sell",
                   "resources_for_followup")
    for field in brain_owned:
        if field in pack:
            errs.append(f"Brain-owned field must NOT be in knowledge pack: "
                        f"{field} (lives in Business Brain only)")
    maturity = pack.get("digital_maturity")
    maturity_value = maturity.get("value") if isinstance(maturity, dict) \
        else maturity
    if maturity_value and normalize(maturity_value) not in \
            tuple(normalize(m) for m in DIGITAL_MATURITY):
        errs.append(f"invalid digital_maturity: {maturity_value!r}")
    # forbid AmanCode pricing-authority / script / claim leakage in packs.
    # These target *authority signals*, not benign English/Arabic words such as
    # a restaurant "menu" or "stock".
    low = str(pack).lower()
    _PRICE_FIG = re.compile(r"\d[\d,.]*\s*(usd|sar|myr|sgd|idr|ريال|دولار|us\$)")
    if _PRICE_FIG.search(low):
        errs.append("forbidden content leaked into pack: numeric price figure")
    for forbidden in ("pricing", "discount", "guarantee", "must-have",
                      "must have", "script", "سعر نهائي", "أسعارنا",
                      "التكلفة"):
        if forbidden in low:
            errs.append(f"forbidden content leaked into pack: {forbidden!r}")
    return errs
