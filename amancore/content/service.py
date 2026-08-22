"""Content library — content_items CRUD + duplicate detection."""

from __future__ import annotations

import hashlib
from typing import Any

from ..errors import NotFoundError
from ..ids import new_id, utcnow
from ..storage.db import Database

CONTENT_STATUSES = {"draft", "review", "approved", "rejected", "archived"}


def content_hash(topic: str = "", angle: str = "", hook: str = "", body: str = "") -> str:
    normalized = "|".join((topic or "", angle or "", hook or "", (body or "")[:500])).lower().strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class ContentService:
    def __init__(self, db: Database):
        self.db = db

    def create(self, **fields: Any) -> str:
        content_id = new_id()
        now = utcnow()
        fields.setdefault("status", "draft")
        fields.setdefault("content_hash", content_hash(
            fields.get("topic"), fields.get("angle"), fields.get("hook"), fields.get("body")
        ))
        cols = ["content_id", "created_at", "updated_at"]
        vals: list[Any] = [content_id, now, now]
        for k, v in fields.items():
            if v is None:
                continue
            cols.append(k)
            vals.append(v)
        self.db.execute(
            f"INSERT INTO content_items ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
            tuple(vals),
        )
        self.db.commit()
        return content_id

    def get(self, content_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM content_items WHERE content_id = ?", (content_id,)).fetchone()
        return dict(row) if row else None

    def update(self, content_id: str, **fields: Any) -> None:
        if not fields:
            return
        if self.get(content_id) is None:
            raise NotFoundError(f"content {content_id} not found")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE content_items SET {', '.join(sets)}, updated_at = ? WHERE content_id = ?",
            (*fields.values(), utcnow(), content_id),
        )
        self.db.commit()

    def search(self, market: str | None = None, language: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM content_items WHERE 1=1"
        params: list[Any] = []
        if market:
            sql += " AND market = ?"
            params.append(market)
        if language:
            sql += " AND language = ?"
            params.append(language)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def find_duplicate(self, topic: str = "", angle: str = "", hook: str = "", body: str = "", content_hash_value: str = "") -> list[dict]:
        h = content_hash_value or content_hash(topic=topic, angle=angle, hook=hook, body=body)
        rows = self.db.execute(
            "SELECT * FROM content_items WHERE content_hash = ?", (h,)
        ).fetchall()
        return [dict(r) for r in rows]
