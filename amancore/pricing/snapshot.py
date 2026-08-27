"""Pricing Snapshot store — immutable approved-price record.

Once the owner approves a price, the snapshot is frozen: later Business Brain
changes must NOT alter the approved offer.
"""

from __future__ import annotations

import json

from ..ids import new_id, utcnow
from ..storage.db import Database


class PricingSnapshotStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        opportunity_id: str,
        pricing_result: dict,
        approved_price: float,
        approved_by: str,
        business_brain_version: int,
        expiration_at: str | None = None,
        scope_fingerprint: str | None = None,
    ) -> str:
        snapshot_id = new_id()
        self.db.execute(
            "INSERT INTO pricing_snapshots "
            "(snapshot_id, opportunity_id, pricing_version, business_brain_version, inputs, "
            " calculated_result, approved_price, currency, approved_by, approved_at, "
            " expiration_at, status, scope_fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
            (
                snapshot_id,
                opportunity_id,
                pricing_result.get("pricing_policy_version", "v1"),
                business_brain_version,
                json.dumps({"scope": pricing_result.get("project_id"), "hours": pricing_result.get("estimated_hours")}, ensure_ascii=False),
                json.dumps(pricing_result, ensure_ascii=False),
                approved_price,
                pricing_result.get("currency", "USD"),
                approved_by,
                utcnow(),
                expiration_at,
                scope_fingerprint,
                utcnow(),
            ),
        )
        self.db.commit()
        return snapshot_id

    def get(self, snapshot_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM pricing_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["calculated_result"] = json.loads(d.get("calculated_result") or "{}")
        return d

    def get_for_opportunity(self, opportunity_id: str) -> dict | None:
        """Most recent ACTIVE (approved) snapshot for an opportunity."""
        row = self.db.execute(
            "SELECT * FROM pricing_snapshots WHERE opportunity_id = ? "
            "AND status != 'superseded' ORDER BY created_at DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["calculated_result"] = json.loads(d.get("calculated_result") or "{}")
        return d

    def supersede(self, snapshot_id: str, superseded_by: str | None = None) -> None:
        """Freeze the old snapshot as superseded — it is never mutated in place;
        a scope change creates a NEW snapshot and marks the previous one done."""
        self.db.execute(
            "UPDATE pricing_snapshots SET status = 'superseded', "
            "superseded_at = ?, superseded_by = ? WHERE snapshot_id = ?",
            (utcnow(), superseded_by, snapshot_id),
        )
        self.db.commit()
