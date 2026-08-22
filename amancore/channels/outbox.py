"""Message Outbox + worker — queued external sends, never direct from agents."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..storage.db import Database

STATUSES = {"queued", "processing", "sent", "failed", "dead", "cancelled"}


class MessageOutbox:
    def __init__(self, db: Database, max_attempts: int = 3, retry_backoff_seconds: int = 10):
        self.db = db
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def enqueue(
        self,
        channel: str,
        recipient: str,
        message_type: str,
        payload,
        idempotency_key: str | None = None,
        lead_id: str | None = None,
        conversation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        message_id = new_id()
        now = utcnow()
        self.db.execute(
            "INSERT INTO message_outbox "
            "(message_id, channel, recipient, message_type, payload, idempotency_key, "
            " status, attempts, next_attempt_at, lead_id, conversation_id, correlation_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)",
            (
                message_id, channel, recipient, message_type,
                json.dumps(payload, ensure_ascii=False), idempotency_key,
                now, lead_id, conversation_id, correlation_id, now,
            ),
        )
        self.db.commit()
        return message_id

    def get(self, message_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM message_outbox WHERE message_id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.get("payload") or "{}")
        return d

    def has_success_for(self, idempotency_key: str) -> bool:
        if not idempotency_key:
            return False
        row = self.db.execute(
            "SELECT 1 FROM message_outbox WHERE idempotency_key = ? AND status = 'sent'",
            (idempotency_key,),
        ).fetchone()
        return row is not None

    def next_ready(self, limit: int = 10) -> list[dict]:
        now = utcnow()
        rows = self.db.execute(
            "SELECT * FROM message_outbox WHERE status = 'queued' AND next_attempt_at <= ? "
            "ORDER BY created_at LIMIT ?",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_processing(self, message_id: str) -> None:
        self.db.execute("UPDATE message_outbox SET status = 'processing' WHERE message_id = ?", (message_id,))
        self.db.commit()

    def mark_sent(self, message_id: str, provider_message_id: str | None = None) -> None:
        self.db.execute(
            "UPDATE message_outbox SET status = 'sent', sent_at = ?, provider_message_id = ? WHERE message_id = ?",
            (utcnow(), provider_message_id, message_id),
        )
        self.db.commit()

    def mark_failed(self, message_id: str, reason: str) -> None:
        msg = self.get(message_id) or {}
        attempts = msg.get("attempts", 0) + 1
        if attempts >= self.max_attempts:
            self.db.execute(
                "UPDATE message_outbox SET status = 'dead', attempts = ?, failure_reason = ? WHERE message_id = ?",
                (attempts, reason, message_id),
            )
        else:
            backoff = timedelta(seconds=self.retry_backoff_seconds * attempts)
            next_at = (datetime.now(timezone.utc) + backoff).isoformat()
            self.db.execute(
                "UPDATE message_outbox SET status = 'queued', attempts = ?, next_attempt_at = ?, failure_reason = ? "
                "WHERE message_id = ?",
                (attempts, next_at, reason, message_id),
            )
        self.db.commit()

    def cancel(self, message_id: str) -> None:
        self.db.execute("UPDATE message_outbox SET status = 'cancelled' WHERE message_id = ?", (message_id,))
        self.db.commit()

    def counts(self) -> dict:
        rows = self.db.execute(
            "SELECT status, COUNT(*) AS c FROM message_outbox GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}


class OutboxWorker:
    """Processes queued messages through channel adapters (mock-safe)."""

    def __init__(self, outbox: MessageOutbox, adapters: dict, policy, audit=None, dispatcher=None):
        self.outbox = outbox
        self.adapters = adapters
        self.policy = policy
        self.audit = audit
        self.dispatcher = dispatcher

    def process_one(self, message: dict) -> dict:
        channel = message["channel"]
        adapter = self.adapters.get(channel)
        if adapter is None:
            self.outbox.mark_failed(message["message_id"], f"no adapter for {channel}")
            return {"message_id": message["message_id"], "status": "failed", "reason": "no adapter"}

        # policy gate (deny → cancel; approval_required → hold)
        decision = self.policy.evaluate_send(channel, message["message_type"], "low")
        if decision == "deny":
            self.outbox.cancel(message["message_id"])
            return {"message_id": message["message_id"], "status": "cancelled", "reason": "policy deny"}
        if decision == "approval_required":
            return {"message_id": message["message_id"], "status": "queued", "reason": "approval required"}

        self.outbox.mark_processing(message["message_id"])
        try:
            result = adapter.send(message["recipient"], message["message_type"], message["payload"])
            self.outbox.mark_sent(message["message_id"], result.get("provider_message_id"))
            self._emit("whatsapp.message.sent" if channel == "whatsapp" else "message.sent", message)
            self._audit("channel.sent", channel, result=str(result))
            return {"message_id": message["message_id"], "status": "sent", "provider_message_id": result.get("provider_message_id")}
        except Exception as exc:  # noqa: BLE001
            self.outbox.mark_failed(message["message_id"], str(exc))
            self._emit("message.failed", message)
            self._audit("channel.failed", channel, result=str(exc))
            return {"message_id": message["message_id"], "status": "failed", "reason": str(exc)}

    def drain(self, limit: int = 10) -> list[dict]:
        results = []
        for msg in self.outbox.next_ready(limit):
            results.append(self.process_one(msg))
        return results

    def _emit(self, event_type: str, message: dict) -> None:
        if self.dispatcher is None:
            return
        from ..services.events import CanonicalEvent

        self.dispatcher.publish(
            CanonicalEvent(
                event_id=new_id(),
                event_type=event_type,
                timestamp=utcnow(),
                source="outbox",
                actor_type="system",
                correlation_id=message.get("correlation_id"),
                payload={"message_id": message.get("message_id"), "channel": message.get("channel")},
            )
        )

    def _audit(self, action: str, resource: str, **fields) -> None:
        if self.audit is not None:
            self.audit.record(action=action, resource=resource, **fields)
