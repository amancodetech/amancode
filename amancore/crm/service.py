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

    def find_lead_by_whatsapp(self, wa_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM leads WHERE contact_whatsapp = ? ORDER BY created_at DESC LIMIT 1", (wa_id,)
        ).fetchone()
        return _row(row)

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
