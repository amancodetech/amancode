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

    def delete_test_lead(self, wa_id: str) -> None:
        """Remove a TEST lead + conversations (smoke tests only — never real leads)."""
        lead = self.find_lead_by_whatsapp(wa_id)
        if lead is None:
            return
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
