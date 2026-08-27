"""Knowledge Layer — validator.

Validates the versioned ``knowledge/`` packs (industry extensions and the
interaction-rules pack) against :mod:`knowledge.schema`. Run standalone:

    python3 -m knowledge.validator

Non-zero exit + printed errors if any pack is invalid. Also exposes
``validate_all(root)`` returning ``(ok: bool, errors: dict)`` for runtime/tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from . import schema


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def validate_industry_pack(path: Path) -> list[str]:
    data = _load_yaml(path)
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
