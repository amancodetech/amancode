"""CRM Data Service — the ONLY controlled gateway to CRM tables.

Agents must call these operations; they never mutate database tables
directly. All writes are parameterized and timestamped.
"""

from __future__ import annotations

from typing import Any

from ..errors import CRMError, NotFoundError
from ..ids import new_id, utcnow
from ..storage.db import Database


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


class CRMService:
    def __init__(self, db: Database):
        self.db = db

    # ---- Leads ---------------------------------------------------------
    def create_lead(self, **fields: Any) -> str:
        lead_id = new_id()
        now = utcnow()
        cols = ["lead_id", "created_at", "updated_at"]
        vals: list[Any] = [lead_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        placeholders = ", ".join("?" for _ in vals)
        self.db.execute(
            f"INSERT INTO leads ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
        self.db.commit()
        return lead_id

    def update_lead(self, lead_id: str, **fields: Any) -> None:
        if not fields:
            return
        if self.get_lead(lead_id) is None:
            raise NotFoundError(f"lead {lead_id} not found")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE leads SET {', '.join(sets)}, updated_at = ? WHERE lead_id = ?",
            (*fields.values(), utcnow(), lead_id),
        )
        self.db.commit()

    def get_lead(self, lead_id: str) -> dict | None:
        return _row(self.db.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone())

    def search_leads(
        self, query: str | None = None, stage: str | None = None, limit: int = 50
    ) -> list[dict]:
        sql = "SELECT * FROM leads WHERE 1=1"
        params: list[Any] = []
        if query:
            sql += " AND (name LIKE ? OR company LIKE ? OR contact_email LIKE ?)"
            like = f"%{query}%"
            params += [like, like, like]
        if stage:
            sql += " AND lead_stage = ?"
            params.append(stage)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def find_lead(self, company: str | None = None, website: str | None = None) -> list[dict]:
        """Dedup lookup by exact company name and/or website domain."""
        sql = "SELECT * FROM leads WHERE 1=1"
        params: list[Any] = []
        if company:
            sql += " AND company = ?"
            params.append(company)
        if website:
            sql += " AND (website = ? OR contact_website = ?)"
            params += [website, website]
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    # ---- Channel-neutral identity resolution ----------------------------
    def find_lead_by_identity(self, channel: str, external_user_id: str) -> dict | None:
        """Canonical lookup: platform_identities → leads (exact match)."""
        row = self.db.execute(
            "SELECT l.* FROM platform_identities i"
            " JOIN leads l ON l.lead_id = i.lead_id"
            " WHERE i.channel = ? AND i.external_user_id = ?"
            " ORDER BY l.created_at DESC LIMIT 1",
            ((channel or "").lower(), external_user_id),
        ).fetchone()
        return _row(row)

    def add_lead_identity(self, lead_id: str, channel: str, external_user_id: str,
                          external_username: str | None = None,
                          is_primary: bool = False) -> str | None:
        """Attach a channel identity to a lead. Idempotent; returns identity_id
        (existing one on conflict). Never merges leads automatically."""
        if not (external_user_id or "").strip():
            return None
        now = utcnow()
        existing = self.db.execute(
            "SELECT identity_id, lead_id FROM platform_identities"
            " WHERE channel = ? AND external_user_id = ?",
            ((channel or "").lower(), external_user_id),
        ).fetchone()
        if existing is not None:
            return existing["identity_id"] if existing["lead_id"] == lead_id else None
        identity_id = new_id()
        self.db.execute(
            "INSERT INTO platform_identities "
            "(identity_id, lead_id, channel, external_user_id, external_username,"
            " is_primary, verified, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (identity_id, lead_id, (channel or "").lower(), external_user_id,
             external_username, 1 if is_primary else 0, now, now),
        )
        self.db.commit()
        return identity_id

    def find_lead_by_whatsapp(self, wa_id: str) -> dict | None:
        """LEGACY bridge — delegates to the generic resolver and falls back to
        the historical contact_whatsapp column (pre-identity leads), backfilling
        an identity row so the canonical path owns all future lookups."""
        lead = self.find_lead_by_identity("whatsapp", wa_id)
        if lead is not None:
            return lead
        row = self.db.execute(
            "SELECT * FROM leads WHERE contact_whatsapp = ? ORDER BY created_at DESC LIMIT 1",
            (wa_id,),
        ).fetchone()
        legacy = _row(row)
        if legacy is not None:
            try:
                self.add_lead_identity(legacy["lead_id"], "whatsapp", wa_id,
                                       external_username=legacy.get("name"), is_primary=True)
            except Exception:  # noqa: BLE001 — backfill must never break callers
                pass
        return legacy

    def delete_test_lead(self, wa_id: str) -> None:
        """Remove a TEST lead + conversations + identities (smoke tests only)."""
        lead = self.find_lead_by_whatsapp(wa_id)
        if lead is None:
            return
        self.db.execute("DELETE FROM platform_identities WHERE lead_id = ?", (lead["lead_id"],))
        self.db.execute("DELETE FROM conversations WHERE lead_id = ?", (lead["lead_id"],))
        self.db.execute("DELETE FROM leads WHERE lead_id = ?", (lead["lead_id"],))
        self.db.commit()

    # ---- Customers -----------------------------------------------------
    def create_customer(self, company: str, **fields: Any) -> str:
        customer_id = new_id()
        now = utcnow()
        cols = ["customer_id", "company", "created_at", "updated_at"]
        vals: list[Any] = [customer_id, company, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO customers ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return customer_id

    def update_customer(self, customer_id: str, **fields: Any) -> None:
        if not fields:
            return
        if self.get_customer(customer_id) is None:
            raise NotFoundError(f"customer {customer_id} not found")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE customers SET {', '.join(sets)}, updated_at = ? WHERE customer_id = ?",
            (*fields.values(), utcnow(), customer_id),
        )
        self.db.commit()

    def get_customer(self, customer_id: str) -> dict | None:
        return _row(
            self.db.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        )

    # ---- Opportunities -------------------------------------------------
    def create_opportunity(self, lead_id: str, service: str, **fields: Any) -> str:
        opportunity_id = new_id()
        now = utcnow()
        cols = ["opportunity_id", "lead_id", "service", "created_at", "updated_at"]
        vals: list[Any] = [opportunity_id, lead_id, service, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO opportunities ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return opportunity_id

    def update_opportunity(self, opportunity_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE opportunities SET {', '.join(sets)}, updated_at = ? WHERE opportunity_id = ?",
            (*fields.values(), utcnow(), opportunity_id),
        )
        self.db.commit()

    def get_opportunity_for_lead(self, lead_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM opportunities WHERE lead_id = ? ORDER BY created_at DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return _row(row)

    def get_opportunity(self, opportunity_id: str) -> dict | None:
        return _row(
            self.db.execute(
                "SELECT * FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)
            ).fetchone()
        )

    def won_opportunity(self, opportunity_id: str, company: str, **project_fields: Any) -> dict:
        """Finalize a won deal: create/link customer + project, set stage=won.

        This is what turns a lead into a customer (enables support + analytics).
        Price/scope are NOT changed here — the pricing snapshot is the source.
        """
        opp = self.get_opportunity(opportunity_id)
        if opp is None:
            raise NotFoundError(f"opportunity {opportunity_id} not found")
        customer_id = opp.get("customer_id")
        if not customer_id:
            customer_id = self.create_customer(company=company or "Customer")
            self.db.execute(
                "UPDATE opportunities SET customer_id = ? WHERE opportunity_id = ?",
                (customer_id, opportunity_id),
            )
            self.db.commit()
        project_id = self.create_project(
            customer_id,
            opp.get("service", ""),
            opportunity_id=opportunity_id,
            status=project_fields.pop("status", "active"),
            **project_fields,
        )
        self.update_opportunity(opportunity_id, stage="won", customer_id=customer_id)
        return {"customer_id": customer_id, "project_id": project_id, "opportunity_id": opportunity_id}

    def get_customer_for_lead(self, lead_id: str) -> dict | None:
        """Resolve a customer for a lead via a linked (won) opportunity."""
        row = self.db.execute(
            "SELECT c.* FROM customers c "
            "JOIN opportunities o ON o.customer_id = c.customer_id "
            "WHERE o.lead_id = ? ORDER BY o.updated_at DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return _row(row)

    def get_projects_for_customer(self, customer_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM projects WHERE customer_id = ? ORDER BY created_at DESC",
                (customer_id,),
            ).fetchall()
        ]

    def get_care_plans_for_customer(self, customer_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM care_plans WHERE customer_id = ? ORDER BY created_at DESC",
                (customer_id,),
            ).fetchall()
        ]

    # ---- Projects ------------------------------------------------------
    def create_project(self, customer_id: str, service: str, **fields: Any) -> str:
        project_id = new_id()
        now = utcnow()
        cols = ["project_id", "customer_id", "service", "created_at", "updated_at"]
        vals: list[Any] = [project_id, customer_id, service, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO projects ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return project_id

    def update_project(self, project_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE projects SET {', '.join(sets)}, updated_at = ? WHERE project_id = ?",
            (*fields.values(), utcnow(), project_id),
        )
        self.db.commit()

    # ---- Care Plans ----------------------------------------------------
    def create_care_plan(self, customer_id: str, plan_tier: str, **fields: Any) -> str:
        care_plan_id = new_id()
        now = utcnow()
        cols = ["care_plan_id", "customer_id", "plan_tier", "created_at", "updated_at"]
        vals: list[Any] = [care_plan_id, customer_id, plan_tier, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO care_plans ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return care_plan_id

    # ---- Conversations -------------------------------------------------
    def append_conversation(self, lead_id: str, channel: str, **fields: Any) -> str:
        conversation_id = new_id()
        now = utcnow()
        cols = ["conversation_id", "lead_id", "channel", "created_at", "updated_at"]
        vals: list[Any] = [conversation_id, lead_id, channel, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO conversations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict | None:
        return _row(
            self.db.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        )

    def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        if not fields:
            return
        if self.get_conversation(conversation_id) is None:
            raise NotFoundError(f"conversation {conversation_id} not found")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE conversations SET {', '.join(sets)}, updated_at = ? WHERE conversation_id = ?",
            (*fields.values(), utcnow(), conversation_id),
        )
        self.db.commit()

    def get_conversation_for_lead(self, lead_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM conversations WHERE lead_id = ? ORDER BY created_at DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return _row(row)

    # ---- Research results ---------------------------------------------
    def create_research_result(self, **fields: Any) -> str:
        research_result_id = new_id()
        now = utcnow()
        cols = ["research_result_id", "created_at"]
        vals: list[Any] = [research_result_id, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO research_results ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return research_result_id

    def list_research_results(self, type_: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM research_results WHERE 1=1"
        params: list[Any] = []
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    # ── Requirements Intelligence Layer (RIL) Gateway ────────────────────
    def create_requirement(self, **fields: Any) -> str:
        requirement_id = fields.pop("requirement_id", None) or new_id()
        now = utcnow()
        cols = ["requirement_id", "first_seen_at", "last_seen_at", "created_at", "updated_at"]
        vals: list[Any] = [requirement_id, now, now, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        placeholders = ", ".join("?" for _ in vals)
        self.db.execute(
            f"INSERT INTO requirements ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
        self.db.commit()
        return requirement_id

    def update_requirement(self, requirement_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE requirements SET {', '.join(sets)} WHERE requirement_id = ?",
            (*fields.values(), requirement_id),
        )
        self.db.commit()

    def get_requirement(self, requirement_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM requirements WHERE requirement_id = ?", (requirement_id,)).fetchone()
        return _row(row)

    def list_requirements_for_lead(self, lead_id: str, category: str | None = None) -> list[dict]:
        sql = "SELECT * FROM requirements WHERE lead_id = ?"
        params: list[Any] = [lead_id]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY created_at ASC"
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def list_requirements_for_project(self, project_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM requirements WHERE project_id = ? ORDER BY created_at ASC", (project_id,)
        ).fetchall()]

    def create_conflict(self, **fields: Any) -> str:
        conflict_id = fields.pop("conflict_id", None) or new_id()
        now = utcnow()
        cols = ["conflict_id", "created_at"]
        vals: list[Any] = [conflict_id, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO requirement_conflicts ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return conflict_id

    def resolve_conflict(self, conflict_id: str, resolution: str) -> None:
        self.db.execute(
            "UPDATE requirement_conflicts SET status = 'resolved', resolution = ?, resolved_at = ? WHERE conflict_id = ?",
            (resolution, utcnow(), conflict_id),
        )
        self.db.commit()

    def list_conflicts_for_lead(self, lead_id: str, status: str = "open") -> list[dict]:
        sql = "SELECT * FROM requirement_conflicts WHERE lead_id = ?"
        params: list[Any] = [lead_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC"
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def create_decision(self, **fields: Any) -> str:
        decision_id = fields.pop("decision_id", None) or new_id()
        now = utcnow()
        cols = ["decision_id", "created_at", "updated_at"]
        vals: list[Any] = [decision_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO project_decisions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return decision_id

    def list_decisions_for_lead(self, lead_id: str, status: str | None = "active") -> list[dict]:
        sql = "SELECT * FROM project_decisions WHERE lead_id = ?"
        params: list[Any] = [lead_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC"
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def create_open_question(self, **fields: Any) -> str:
        question_id = fields.pop("question_id", None) or new_id()
        now = utcnow()
        cols = ["question_id", "created_at", "updated_at"]
        vals: list[Any] = [question_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO open_questions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return question_id

    def update_open_question(self, question_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow()
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE open_questions SET {', '.join(sets)} WHERE question_id = ?",
            (*fields.values(), question_id),
        )
        self.db.commit()

    def list_open_questions_for_lead(self, lead_id: str, status: str | None = "open") -> list[dict]:
        sql = "SELECT * FROM open_questions WHERE lead_id = ?"
        params: list[Any] = [lead_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, created_at ASC"
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def get_next_open_question(self, lead_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM open_questions WHERE lead_id = ? AND status = 'open' ORDER BY priority DESC, created_at ASC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return _row(row)

    def create_project_scope(self, **fields: Any) -> str:
        scope_id = fields.pop("scope_id", None) or new_id()
        now = utcnow()
        cols = ["scope_id", "created_at", "updated_at"]
        vals: list[Any] = [scope_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO project_scopes ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return scope_id

    def get_project_scope_for_lead(self, lead_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM project_scopes WHERE lead_id = ? ORDER BY created_at DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return _row(row)

    def create_scope_version(self, **fields: Any) -> str:
        version_id = fields.pop("version_id", None) or new_id()
        now = utcnow()
        cols = ["version_id", "created_at", "updated_at"]
        vals: list[Any] = [version_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO scope_versions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return version_id

    def get_latest_scope_version(self, scope_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM scope_versions WHERE scope_id = ? ORDER BY version_number DESC LIMIT 1",
            (scope_id,),
        ).fetchone()
        return _row(row)

    def add_scope_item(self, **fields: Any) -> str:
        item_id = fields.pop("item_id", None) or new_id()
        now = utcnow()
        cols = ["item_id", "created_at"]
        vals: list[Any] = [item_id, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO scope_items ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return item_id

    def list_scope_items(self, version_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM scope_items WHERE version_id = ? ORDER BY sort_order ASC, created_at ASC",
            (version_id,),
        ).fetchall()]

