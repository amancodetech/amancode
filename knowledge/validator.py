"""Knowledge Layer — validator.

Validates the versioned ``knowledge/`` packs (industry extensions and the
interaction-rules pack) against :mod:`knowledge.schema`. Run standalone:

    python3 -m knowledge.validator

Non-zero exit + printed errors if any pack is invalid. Also exposes
``validate_all(root)`` returning ``(ok: bool, errors: dict)`` for runtime/tests.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from . import schema


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# P1-2 §6 — type-aware validation. Meta-packs (e.g. service_details) extend
# the Brain SERVICES catalog rather than one industry profile: they carry
# their own envelope and must NOT be forced to pad industry-only extension
# fields with empty filler. Industry packs keep the exact legacy envelope —
# an incomplete industry pack still fails exactly as before.
_META_PACK_IDS = {"service_details", "service_meta_pack"}
# P1-final §3/§5 — non-industry meta-packs (type-aware validation).
_META_PACK_IDS |= {"decision_roles", "standards_web"}
_REQUIRED_META_PACK_FIELDS = ("id", "brain_profile_id", "version",
                              "last_verified", "sources")
_META_BRAIN_OWNED = ("aliases", "goals", "typical_sections", "features",
                     "conversion", "trust_needs", "objections",
                     "relevant_services", "cross_sell", "resources_for_followup")
_PRICE_FIG = re.compile(r"\d[\d,.]*\s*(usd|sar|myr|sgd|idr|ريال|دولار|us\$)",
                        re.IGNORECASE)
_META_FORBIDDEN = ("pricing", "discount", "guarantee", "must-have",
                   "must have", "script", "سعر نهائي", "أسعارنا", "التكلفة")


def _meta_pack_errors(pack: dict) -> list[str]:
    errs: list[str] = []
    for field in _REQUIRED_META_PACK_FIELDS:
        if field not in pack:
            errs.append(f"pack missing field: {field}")
    if pack.get("id") != pack.get("brain_profile_id"):
        errs.append(f"pack id {pack.get('id')!r} != brain_profile_id "
                    f"{pack.get('brain_profile_id')!r}")
    for field in _META_BRAIN_OWNED:
        if field in pack:
            errs.append(f"Brain-owned field must NOT be in knowledge pack: "
                        f"{field} (lives in Business Brain only)")
    low = str(pack).lower()
    if _PRICE_FIG.search(low):
        errs.append("forbidden content leaked into pack: numeric price figure")
    for forbidden in _META_FORBIDDEN:
        if forbidden in low:
            errs.append(f"forbidden content leaked into pack: {forbidden!r}")
    # service records must be honest about their epistemic status
    sd = pack.get("service_details")
    records = (sd.get("services") if isinstance(sd, dict)
               else sd) or []
    for i, rec in enumerate(records):
        kind = (rec or {}).get("statement_kind", "")
        if str(kind).strip().upper() != "RECOMMENDATION":
            errs.append(f"service_details[{i}] statement_kind must be "
                        f"RECOMMENDATION, got {kind!r}")
        prov = (rec or {}).get("provenance") or {}
        if not isinstance(prov, dict) or not prov.get("source_ref"):
            errs.append(f"service_details[{i}] provenance.source_ref missing")

    # P1-final §3/§5 — generic epistemic-stability walk (meta-packs).
    # Every node carrying statement_kind must declare RECOMMENDATION, or
    # FACT **only inside the standards_web pack** (world-standard facts,
    # never AmanCode claims) — and always with a provenance source_ref.
    fact_pack_id = {"standards_web"}
    allowed_kinds = {"RECOMMENDATION"} | (
        fact_pack_id and {"RECOMMENDATION", "FACT"} if
        pack.get("id") in fact_pack_id else set())

    def _walk(node, path):
        if isinstance(node, dict):
            kind = node.get("statement_kind")
            if kind is not None:
                k = str(kind).strip().upper()
                if k not in allowed_kinds:
                    errs.append(f"{path} statement_kind {k!r} not permitted "
                                f"in this pack (allowed: "
                                f"{sorted(allowed_kinds)})")
                prov = node.get("provenance") or {}
                if not isinstance(prov, dict) or not prov.get("source_ref"):
                    errs.append(f"{path} provenance.source_ref missing")
            for key, val in node.items():
                _walk(val, f"{path}.{key}")
        elif isinstance(node, list):
            for j, item in enumerate(node):
                _walk(item, f"{path}[{j}]")

    _walk(pack, "pack")
    return errs


def validate_industry_pack(path: Path) -> list[str]:
    data = _load_yaml(path)
    if data.get("id") in _META_PACK_IDS or \
            data.get("type") in ("service_details", "service_meta_pack"):
        return _meta_pack_errors(data)
    return schema.pack_errors(data)


def validate_interaction_rules(path: Path) -> list[str]:
    data = _load_yaml(path)
    errs: list[str] = []
    rules = data.get("rules") or []
    if "version" not in data:
        errs.append("interaction pack missing top-level version")
    for i, rec in enumerate(rules):
        for e in schema.record_errors(rec, rule=True):
            errs.append(f"rule[{i}] {e}")
    return errs


def validate_all(root: Path) -> tuple[bool, dict[str, list[str]]]:
    root = Path(root)
    errors: dict[str, list[str]] = {}
    packs_dir = root / "packs"
    for path in sorted(packs_dir.glob("*.yaml")):
        errs = validate_industry_pack(path)
        if errs:
            errors[path.name] = errs
    interaction = root / "interaction"
    for path in sorted(interaction.glob("interaction_rules*.yaml")):
        errs = validate_interaction_rules(path)
        if errs:
            errors[path.name] = errs
    return (not errors), errors


def main() -> int:
    root = Path(__file__).resolve().parent
    ok, errors = validate_all(root)
    if not ok:
        print("KNOWLEDGE VALIDATION FAILED")
        for name, errs in errors.items():
            print(f"  {name}:")
            for e in errs:
                print(f"    - {e}")
        return 1
    print("knowledge: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
