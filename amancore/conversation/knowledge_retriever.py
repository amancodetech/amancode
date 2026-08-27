"""KnowledgeRetriever — contextual slicing of the knowledge layer.

Responsibility is retrieval/slicing ONLY:
  * returns the *relevant* slice of knowledge for a request
    ``(industry, service, language, size, stage)`` — never the whole KB.
  * merges a Business Brain industry profile with its knowledge-pack extension
    into one small slice.
  * treats retrieved content as TAGGED DATA, not instructions (prompt-injection
    safe): only a fixed allow-list of extension fields is ever returned, and
    provenance/URL/license metadata is kept out of the returned slice so it can
    never reach a customer-facing reply.

This module does NOT:
  * decide mode/stage (planner owns that)
  * compute or return pricing
  * decide approvals
  * change service identity
  * write to the CRM
  * send messages
  * dump the whole KB into a prompt
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Only these extension fields may ever be returned as data to the planner.
# Provenance / source / license / url are NEVER returned in the customer slice.
_EXTENSION_FIELDS = (
    "common_processes", "common_pain_points", "decision_roles",
    "digital_maturity", "typical_integrations", "isic_refs",
)
_FALLBACK_INDUSTRY = "generic_business"


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — missing/corrupt pack must not break a turn
        return {}


def _value(v):
    """Normalize a single extension value (dict or scalar) to a small datum."""
    if isinstance(v, dict):
        return {"process": v.get("process") or v.get("integration")
                or v.get("pain") or v.get("code") or v.get("schema") or ""}
    return v


def _strip(items):
    """Reduce a list of {..., source: ...} items to their data payloads only."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            keep = {k: it.get(k) for k in
                    ("process", "pain", "integration", "code", "label",
                     "schema") if it.get(k)}
            if keep:
                out.append(keep)
        elif it:
            out.append(it)
    return out


class KnowledgeRetriever:
    def __init__(self, root: Path | None = None, brain_store=None):
        self._root = Path(root) if root else None
        self._brain_store = brain_store
        self._packs: dict | None = None

    # ---- loading (lazy, cached, graceful) -------------------------------
    @property
    def packs(self) -> dict:
        if self._packs is None:
            self._packs = self._load_packs()
        return self._packs

    def _load_packs(self) -> dict:
        if self._root is None:
            return {}
        packs_dir = self._root / "packs"
        if not packs_dir.is_dir():
            return {}
        out: dict = {}
        for path in sorted(packs_dir.glob("*.yaml")):
            data = _load_yaml(path)
            pid = data.get("id") or data.get("brain_profile_id") or \
                path.stem
            out[pid] = data
        return out

    # ---- retrieval --------------------------------------------------------
    def retrieve(self, industry: str | None = None, service: str | None = None,
                 language: str | None = None, size: str | None = None,
                 stage: str | None = None, brain_profile: dict | None = None,
                 include_source_refs: bool = False) -> dict:
        """Return a small merged slice (Brain profile + pack extension).

        ``include_source_refs`` (default False) toggles provenance references;
        it is intended for internal/audit use only and must never be enabled
        when composing a customer-facing reply.
        """
        industry = industry or _FALLBACK_INDUSTRY
        pack = self.packs.get(industry) or self.packs.get(_FALLBACK_INDUSTRY) \
            or {}

        # 1) build the DATA-only extension slice (allow-list).
        ext: dict = {}
        for field in _EXTENSION_FIELDS:
            val = pack.get(field)
            if val is None:
                continue
            if isinstance(val, list):
                ext[field] = _strip(val)
            elif isinstance(val, dict):
                if "value" in val:  # digital_maturity: {value, note, source}
                    ext[field] = {"value": val.get("value"),
                                  "note": val.get("note") if
                                  include_source_refs else None}
                    if not ext[field]["note"]:
                        ext[field].pop("note", None)
                elif set(val).intersection({"likely", "possible", "unknown"}):
                    # decision_roles — keep only the role priors in the
                    # customer slice; strip provenance + note unless requested.
                    roles = {k: val[k] for k in ("likely", "possible", "unknown")
                             if val.get(k)}
                    if include_source_refs and val.get("note"):
                        roles["note"] = val["note"]
                    ext[field] = roles
                else:
                    ext[field] = val
            else:
                ext[field] = val

        # 2) optionally fold in relevant Brain profile data (reference only —
        #    the Brain stays authoritative; we do not duplicate its fields).
        merged = {
            "industry": industry,
            "brain_profile_id": pack.get("brain_profile_id") or industry,
            "has_extension": bool(pack),
            "extension": ext,
        }
        if brain_profile is not None and isinstance(brain_profile, dict):
            merged["brain_profile"] = {
                k: brain_profile.get(k) for k in
                ("id", "goals", "typical_sections", "features", "conversion",
                 "trust_needs", "objections", "relevant_services",
                 "cross_sell") if brain_profile.get(k)
            }
        if include_source_refs and pack.get("sources"):
            merged["source_refs"] = [s.get("ref") for s in pack["sources"]
                                     if isinstance(s, dict)]
        return merged

    def reload(self) -> None:
        self._packs = None
