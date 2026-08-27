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

# P1-2 §3 — prompt diet: per-mode allow-lists. A mode never receives data it
# does not use. ``None`` value = legacy full slice (only for unknown/None
# modes, so behaviour is unchanged when mode is not threaded through).
_MODE_EXT_SLICE: dict[str, tuple | None] = {
    "NEED": ("common_pain_points",),
    "SHAPING": (),
    "COMMERCIAL": (),          # PRICE/T1 band path — no pack payloads
    "OFFER": (),               # objection ladder lives in Brain profile
    "NEGOTIATION": (),
}
_MODE_BRAIN_SLICE: dict[str, tuple | None] = {
    "NEED": ("id", "goals"),
    "SHAPING": ("id", "typical_sections", "features"),
    # OBJECTION row + relevant service only
    "OFFER": ("id", "objections", "relevant_services"),
    "NEGOTIATION": ("id", "objections", "relevant_services"),
    "COMMERCIAL": ("id",),     # price ask: the name is usually all it needs
}


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
                 include_source_refs: bool = False,
                 mode: str | None = None) -> dict:
        """Return a small merged slice (Brain profile + pack extension).

        ``include_source_refs`` (default False) toggles provenance references;
        it is intended for internal/audit use only and must never be enabled
        when composing a customer-facing reply.

        P1-2 §3: ``mode`` narrows the slice further (prompt diet). Known
        modes get only the fields listed in _MODE_*_SLICE; unknown/None keeps
        the legacy full slice.
        """
        industry = industry or _FALLBACK_INDUSTRY
        pack = self.packs.get(industry) or self.packs.get(_FALLBACK_INDUSTRY) \
            or {}
        ext_allowed = (_MODE_EXT_SLICE.get(mode)
                       if mode in _MODE_EXT_SLICE else None)
        brain_allowed = (_MODE_BRAIN_SLICE.get(mode)
                         if mode in _MODE_BRAIN_SLICE else None)

        # 1) build the DATA-only extension slice (allow-list).
        ext: dict = {}
        for field in _EXTENSION_FIELDS:
            if ext_allowed is not None and field not in ext_allowed:
                continue
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
            if brain_allowed is None:
                keys = ("id", "goals", "typical_sections", "features",
                        "conversion", "trust_needs", "objections",
                        "relevant_services", "cross_sell")
            else:
                keys = brain_allowed
            merged["brain_profile"] = {
                k: brain_profile.get(k) for k in keys
                if brain_profile.get(k)
            }
        if include_source_refs and pack.get("sources"):
            merged["source_refs"] = [s.get("ref") for s in pack["sources"]
                                     if isinstance(s, dict)]

        # P1-final §3 — decision-roles prior (BANT-lite tone ONLY). Sliced by
        # (industry, size); conservative phrasing travels with the entry.
        roles = self.decision_roles_prior(industry, size)
        if roles:
            merged["decision_roles"] = roles
        return merged

    def decision_roles_prior(self, industry: str | None = None,
                             size: str | int | None = None) -> dict | None:
        """Return the smallest honest prior for qualification TONE, or None.

        ``size`` may be a user count (int) or one of the bucket keys. No CRM
        field is consulted here — the CRM stays the deterministic truth for a
        specific lead; this slice only shapes phrasing."""
        meta = self.packs.get("decision_roles")
        if not isinstance(meta, dict):
            return None
        base = ((meta.get("decision_roles") or {})
                .get("base_matrix") or {})
        bucket = None
        if size is not None:
            n = int(size) if str(size).isdigit() else None
            keys = ("micro_1_4", "small_5_49", "medium_50_249",
                    "large_250_plus")
            if n is None:
                for k in keys:
                    if k.startswith(str(size).lower()[:5]):
                        bucket = base.get(k)
                        break
            else:
                picked = "micro_1_4" if n <= 4 else \
                    "small_5_49" if n <= 49 else \
                    "medium_50_249" if n <= 249 else "large_250_plus"
                bucket = base.get(picked)
        override = ((meta.get("decision_roles") or {})
                    .get("industry_overrides") or {}).get(industry or "")
        if bucket is None and not override:
            return None
        out: dict = {}
        if bucket:
            out["roles"] = {k: v for k, v in (bucket.get("roles") or {}).items()
                            if v}
            out["buying_concerns"] = list(bucket.get("buying_concerns") or [])
            out["tone_hint_ar"] = bucket.get("tone_hint_ar")
            out["size"] = bucket.get("size")
        if override:
            out["industry_note"] = override.get("note")
            out["tone_delta_ar"] = override.get("tone_delta_ar")
        out["kind"] = "RECOMMENDATION"
        out["provenance"] = {"source_ref": "isco08_mg1+internal_smb_priors.v1"}
        return out

    def reload(self) -> None:
        self._packs = None
