"""Insight Memory — persistent store + dedup + expiration.

Deduplicate via fingerprint (type:category:period:segment:entity). Existing
insights with the same fingerprint are UPDATED (trend/evidence refreshed),
never duplicated. Stale insights expire and can be superseded.
"""

from __future__ import annotations

import json

from ..ids import new_id, utcnow
from ..storage.db import Database


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


class InsightMemory:
    def __init__(self, db: Database):
        self.db = db

    # ---- insights ------------------------------------------------------
    def save_insight(self, insight: dict) -> dict:
        """Insert or update (dedup by fingerprint). Returns (insight, updated: bool)."""
        fp = insight.get("fingerprint") or ""
        if fp:
            existing = self.find_by_fingerprint(fp)
            if existing and existing["status"] not in ("superseded", "expired"):
                self.update_insight(
                    existing["insight_id"],
                    summary=insight["summary"],
                    evidence=json.dumps(insight["evidence"], ensure_ascii=False),
                    metrics=json.dumps(insight.get("metrics", {}), ensure_ascii=False),
                    confidence=insight["confidence"],
                    severity=insight["severity"],
                    business_impact=insight.get("business_impact", ""),
                    detected_at=insight["detected_at"],
                    status="new",
                )
                return self.get_insight(existing["insight_id"]), True
        insight_id = insight["insight_id"]
        self.db.execute(
            "INSERT INTO insights (insight_id, type, category, title, summary, evidence, "
            " metrics, period, segment, confidence, severity, business_impact, status, "
            " recommendation_id, related_entities, fingerprint, expires_at, superseded_by, "
            " detected_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                insight_id, insight["type"], insight["category"], insight["title"],
                insight["summary"], json.dumps(insight["evidence"], ensure_ascii=False),
                json.dumps(insight.get("metrics", {}), ensure_ascii=False),
                insight.get("period", ""), insight.get("segment", ""),
                insight["confidence"], insight["severity"], insight.get("business_impact", ""),
                insight["status"], insight.get("recommendation_id"),
                json.dumps(insight.get("related_entities", []), ensure_ascii=False),
                insight.get("fingerprint", ""), insight.get("expires_at"),
                insight.get("superseded_by"), insight["detected_at"], utcnow(), utcnow(),
            ),
        )
        self.db.commit()
        return self.get_insight(insight_id), False

    def get_insight(self, insight_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM insights WHERE insight_id = ?", (insight_id,)).fetchone()
        if row is None:
            return None
        i = dict(row)
        for f, default in (("evidence", {}), ("metrics", {}), ("related_entities", [])):
            try:
                i[f] = json.loads(i.get(f) or "")
            except (json.JSONDecodeError, TypeError):
                i[f] = default
        return i

    def update_insight(self, insight_id: str, **fields) -> None:
        if not fields:
            return
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE insights SET {', '.join(sets)}, updated_at = ? WHERE insight_id = ?",
            (*fields.values(), utcnow(), insight_id),
        )
        self.db.commit()

    def find_by_fingerprint(self, fingerprint: str) -> dict | None:
        return _row(self.db.execute(
            "SELECT * FROM insights WHERE fingerprint = ? ORDER BY created_at DESC LIMIT 1",
            (fingerprint,),
        ).fetchone())

    def list_insights(self, status=None, category=None, confidence=None, limit=100) -> list[dict]:
        sql = "SELECT * FROM insights WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if confidence:
            sql += " AND confidence = ?"
            params.append(confidence)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def expire(self, insight_id: str, superseded_by: str | None = None) -> None:
        self.update_insight(insight_id, status="superseded" if superseded_by else "expired",
                            superseded_by=superseded_by)

    def expire_stale(self) -> int:
        """Expire insights past expires_at (status new/reviewed)."""
        now = utcnow()
        rows = self.db.execute(
            "SELECT insight_id FROM insights WHERE expires_at IS NOT NULL AND expires_at < ? "
            "AND status IN ('new','reviewed')",
            (now,),
        ).fetchall()
        for r in rows:
            self.update_insight(r["insight_id"], status="expired")
        return len(rows)

    # ---- recommendations ----------------------------------------------
    def save_recommendation(self, rec: dict) -> str:
        rid = rec["recommendation_id"]
        self.db.execute(
            "INSERT INTO recommendations (recommendation_id, insight_id, type, title, problem, "
            " evidence, proposed_action, alternatives, expected_benefit, expected_risk, "
            " dependencies, confidence, requires_owner_approval, status, decision, decided_by, "
            " decided_at, approval_id, brain_change_proposal_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid, rec.get("insight_id"), rec["type"], rec["title"], rec["problem"],
                json.dumps(rec["evidence"], ensure_ascii=False), rec["proposed_action"],
                json.dumps(rec.get("alternatives", []), ensure_ascii=False),
                rec.get("expected_benefit", ""), rec.get("expected_risk", ""),
                rec.get("dependencies", ""), rec["confidence"],
                1 if rec["requires_owner_approval"] else 0,
                rec["status"], rec.get("decision"), rec.get("decided_by"),
                rec.get("decided_at"), rec.get("approval_id"),
                rec.get("brain_change_proposal_id"), utcnow(), utcnow(),
            ),
        )
        self.db.commit()
        return rid

    def get_recommendation(self, recommendation_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,)
        ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        for f in ("evidence", "alternatives"):
            try:
                rec[f] = json.loads(rec.get(f) or "[]" if f == "alternatives" else rec.get(f) or "{}")
            except (json.JSONDecodeError, TypeError):
                rec[f] = [] if f == "alternatives" else {}
        return rec

    def update_recommendation(self, recommendation_id: str, **fields) -> None:
        if not fields:
            return
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE recommendations SET {', '.join(sets)}, updated_at = ? WHERE recommendation_id = ?",
            (*fields.values(), utcnow(), recommendation_id),
        )
        self.db.commit()

    def list_recommendations(self, status=None, type_=None, limit=100) -> list[dict]:
        sql = "SELECT * FROM recommendations WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    # ---- decision log ---------------------------------------------------
    def record_decision(self, entity_type: str, entity_id: str, decision: str,
                        decided_by: str, reason: str = "") -> str:
        decision_id = new_id()
        self.db.execute(
            "INSERT INTO decision_log (decision_id, entity_type, entity_id, decision, "
            " decided_by, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (decision_id, entity_type, entity_id, decision, decided_by, reason, utcnow()),
        )
        self.db.commit()
        return decision_id

    def list_decisions(self, entity_id: str | None = None, limit=100) -> list[dict]:
        sql = "SELECT * FROM decision_log WHERE 1=1"
        params: list = []
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]
