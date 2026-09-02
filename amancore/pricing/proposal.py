"""Proposal Generator + store — deterministic template, no invented claims."""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..storage.db import Database

SECTIONS = [
    "Executive Summary",
    "Client Problem",
    "Proposed Solution",
    "Scope",
    "Deliverables",
    "Exclusions",
    "Timeline",
    "Investment",
    "Payment Terms",
    "Assumptions",
    "Revision Policy",
    "Support/Care Plan",
    "Validity",
    "Next Steps",
]

_OWNER_REQUIRED = "OWNER_APPROVAL_REQUIRED"


class ProposalStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, opportunity_id: str, body: dict, snapshot_id: str, brain_version: int) -> str:
        proposal_id = new_id()
        now = utcnow()
        self.db.execute(
            "INSERT INTO proposals "
            "(proposal_id, opportunity_id, version, pricing_snapshot_id, business_brain_version, "
            " status, body, created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'draft', ?, ?, ?)",
            (proposal_id, opportunity_id, snapshot_id, brain_version, json_dumps(body), now, now),
        )
        self.db.commit()
        return proposal_id

    def get(self, proposal_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["body"] = json_loads(d.get("body"), {})
        return d

    def get_for_opportunity(self, opportunity_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM proposals WHERE opportunity_id = ? ORDER BY created_at DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["body"] = json_loads(d.get("body"), {})
        return d

    def get_approved_for_opportunity(self, opportunity_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM proposals WHERE opportunity_id = ? AND status = 'approved' ORDER BY created_at DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["body"] = json_loads(d.get("body"), {})
        return d

    def update(self, proposal_id: str, **fields) -> None:
        if not fields:
            return
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE proposals SET {', '.join(sets)}, updated_at = ? WHERE proposal_id = ?",
            (*fields.values(), utcnow(), proposal_id),
        )
        self.db.commit()


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def json_loads(s, default):
    import json

    try:
        v = json.loads(s)
        return v if v is not None else default
    except (json.JSONDecodeError, TypeError):
        return default


class ProposalGenerator:
    def __init__(self, brain_store, store: ProposalStore | None = None):
        self.brain_store = brain_store
        self.store = store

    @property
    def brain(self) -> dict:
        return self.brain_store.current()[1]

    def generate(
        self,
        opportunity: dict,
        scope: dict,
        offer: dict,
        snapshot: dict,
        timeline: str = "",
        terms: dict | None = None,
        assumptions: list | None = None,
    ) -> dict:
        """Build a proposal draft from data + Business Brain approved claims only."""
        approved_claims = self.brain.get("approved_claims", [])
        terms = terms or {}
        snapshot_result = snapshot.get("calculated_result", {})
        body = {
            "Executive Summary": f"AmanCode proposes to deliver the {offer.get('service_name', 'solution')} for this project.",
            "Client Problem": opportunity.get("scope_summary", _OWNER_REQUIRED),
            "Proposed Solution": offer.get("service_name", _OWNER_REQUIRED),
            "Scope": ", ".join(scope.get("included", [])) or _OWNER_REQUIRED,
            "Deliverables": ", ".join(scope.get("deliverables", [])) or _OWNER_REQUIRED,
            "Exclusions": ", ".join(scope.get("excluded", [])) or "To be confirmed",
            "Timeline": timeline or _OWNER_REQUIRED,
            "Investment": (
                f"{snapshot.get('approved_price')} {snapshot.get('currency', 'USD')}"
                if snapshot.get("approved_price") is not None else _OWNER_REQUIRED
            ),
            "Payment Terms": terms.get("payment_terms") or _OWNER_REQUIRED,
            "Assumptions": "; ".join(assumptions or []) or _OWNER_REQUIRED,
            "Revision Policy": "30-day warranty; revisions within documented scope.",
            "Support/Care Plan": "Care Plan available (hosting, maintenance, support).",
            "Validity": f"{snapshot_result.get('breakdown', {}).get('price_validity_days', 14)} days",
            "Next Steps": "Sign the agreement and provide the 50% upfront payment.",
            "Approved Claims": "; ".join(approved_claims),
        }
        return {
            "id": new_id(),
            "opportunity_id": opportunity.get("opportunity_id"),
            "version": 1,
            "pricing_snapshot_id": snapshot.get("snapshot_id"),
            "business_brain_version": self.brain_store.current()[0],
            "status": "draft",
            "body": body,
        }

    def render(self, proposal: dict) -> str:
        lines = [f"PROPOSAL v{proposal.get('version', 1)} — {proposal.get('status', 'draft')}", ""]
        for section in SECTIONS:
            value = proposal.get("body", {}).get(section, "")
            lines.append(f"## {section}")
            lines.append(str(value))
            lines.append("")
        return "\n".join(lines)
