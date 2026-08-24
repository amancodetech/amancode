"""Message Outbox + worker — queued external sends, never direct from agents."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("channels.outbox")

STATUSES = {"queued", "processing", "sent", "delivered", "read",
            "failed", "dead", "cancelled", "uncertain"}


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
        cur = self.db.execute(
            "INSERT INTO message_outbox "
            "(message_id, channel, recipient, message_type, payload, idempotency_key, "
            " status, attempts, next_attempt_at, lead_id, conversation_id, correlation_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?) "
            "ON CONFLICT(idempotency_key) WHERE idempotency_key IS NOT NULL "
            "DO NOTHING" if idempotency_key else
            "INSERT INTO message_outbox "
            "(message_id, channel, recipient, message_type, payload, idempotency_key, "
            " status, attempts, next_attempt_at, lead_id, conversation_id, correlation_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)",
            (
                message_id, channel, recipient, message_type,
                json.dumps(payload, ensure_ascii=False), idempotency_key,
                now, lead_id, conversation_id, correlation_id, now,
            ) if idempotency_key else (
                message_id, channel, recipient, message_type,
                json.dumps(payload, ensure_ascii=False), idempotency_key,
                now, lead_id, conversation_id, correlation_id, now,
            ),
        )
        if idempotency_key and cur.rowcount == 0:
            # REAUD CRITICAL fix: insert-or-return-existing under the partial
            # unique index — concurrent duplicates collapse to one row.
            existing = self.db.execute(
                "SELECT message_id FROM message_outbox WHERE idempotency_key = ?",
                (idempotency_key,)).fetchone()
            self.db.commit()
            return existing["message_id"]
        self.db.commit()
        return message_id

    def get(self, message_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM message_outbox WHERE message_id = ?", (message_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.get("payload") or "{}")
        return d

    def claim_batch(self, limit: int = 10, stale_after_seconds: int = 300) -> list[dict]:
        """OUT-202 (C1/C4): atomically claim queued rows for exactly one owner.

        Single guarded UPDATE per row (status='queued' predicate) — a losing
        racer's rowcount is 0 and it never sees the message. Stale
        `processing` rows older than stale_after_seconds are revived first,
        so a crash mid-send can never strand a message forever.
        """
        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(seconds=stale_after_seconds)).isoformat()
        # REAUD MEDIUM fix: rows whose provider ACCEPTED (pmid present) are
        # safe to retry; rows without pmid died inside the send window —
        # blind requeue risks duplicates. They go to `uncertain` and wait
        # for human reconciliation (plan §9 MANUAL_ONLY).
        self.db.execute(
            "UPDATE message_outbox SET status = 'uncertain', claimed_at = NULL, "
            "claim_token = NULL, "
            "failure_reason = 'crash window: provider acceptance unknown — "
            "manual reconciliation required' "
            "WHERE status = 'processing' AND claimed_at IS NOT NULL AND claimed_at < ? "
            "AND (provider_message_id IS NULL OR provider_message_id = '')",
            (cutoff,),
        )
        self.db.execute(
            "UPDATE message_outbox SET status = 'queued', "
            "failure_reason = COALESCE(failure_reason, '') || ' [stale-reclaimed]' "
            "WHERE status = 'processing' AND claimed_at IS NOT NULL AND claimed_at < ?",
            (cutoff,),
        )
        unc = self.db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE status='uncertain'"
        ).fetchone()["c"]
        if unc:
            log.warning("outbox.uncertain count=%d — owner reconciliation needed", unc)
        self.db.commit()

        candidates = self.db.execute(
            "SELECT message_id FROM message_outbox WHERE status = 'queued' "
            "AND next_attempt_at <= ? ORDER BY created_at LIMIT ?",
            (utcnow(), limit),
        ).fetchall()
        token, stamp = new_id(), utcnow()
        claimed_ids: list[str] = []
        for r in candidates:
            cur = self.db.execute(
                "UPDATE message_outbox SET status = 'processing', claimed_at = ?, claim_token = ? "
                "WHERE message_id = ? AND status = 'queued'",
                (stamp, token, r["message_id"]),
            )
            if cur.rowcount == 1:
                claimed_ids.append(r["message_id"])
        self.db.commit()
        if not claimed_ids:
            return []
        marks = ",".join("?" * len(claimed_ids))
        out = []
        for row in self.db.execute(
            f"SELECT * FROM message_outbox WHERE message_id IN ({marks})", tuple(claimed_ids)
        ).fetchall():
            d = dict(row)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except (ValueError, TypeError):
                pass
            out.append(d)
        return sorted(out, key=lambda d: d.get("created_at") or "")

    def next_ready(self, limit: int = 10) -> list[dict]:
        now = utcnow()
        rows = self.db.execute(
            "SELECT * FROM message_outbox WHERE status = 'queued' AND next_attempt_at <= ? "
            "ORDER BY created_at LIMIT ?",
            (now, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except (ValueError, TypeError):
                pass
            out.append(d)
        return out

    def mark_processing(self, message_id: str) -> None:
        self.db.execute("UPDATE message_outbox SET status = 'processing' WHERE message_id = ?", (message_id,))
        self.db.commit()

    def mark_sent(self, message_id: str, provider_message_id: str | None = None) -> None:
        self.db.execute(
            "UPDATE message_outbox SET status = 'sent', sent_at = ?, provider_message_id = ? WHERE message_id = ?",
            (utcnow(), provider_message_id, message_id),
        )
        self.db.commit()

    def mark_failed(self, message_id: str, reason: str, *,
                    retry_in_seconds: int | None = None,
                    dead_now: bool = False) -> str:
        """Returns the final status ('dead' or 'queued') so callers can alert.

        WA-302/W1: dead_now short-circuits pointless retries for permanent
        failures (auth/bad_recipient); retry_in_seconds honors provider
        Retry-After instead of fixed linear backoff.
        """
        msg = self.get(message_id) or {}
        attempts = msg.get("attempts", 0) + 1
        reason = (reason or "")[:200]  # OUT-205: bounded forensic field
        if dead_now or attempts >= self.max_attempts:
            self.db.execute(
                "UPDATE message_outbox SET status = 'dead', attempts = ?, failure_reason = ? WHERE message_id = ?",
                (attempts, reason, message_id),
            )
            return "dead"
        if retry_in_seconds is not None and retry_in_seconds > 0:
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=retry_in_seconds)).isoformat()
            self.db.execute(
                "UPDATE message_outbox SET status = 'queued', attempts = ?, next_attempt_at = ?, failure_reason = ? "
                "WHERE message_id = ?",
                (attempts, next_at, reason, message_id),
            )
            return "queued"
            self.db.execute(
                "UPDATE message_outbox SET status = 'dead', attempts = ?, failure_reason = ? WHERE message_id = ?",
                (attempts, reason, message_id),
            )
            return "dead"
        else:
            backoff = timedelta(seconds=self.retry_backoff_seconds * attempts)
            next_at = (datetime.now(timezone.utc) + backoff).isoformat()
            self.db.execute(
                "UPDATE message_outbox SET status = 'queued', attempts = ?, next_attempt_at = ?, failure_reason = ? "
                "WHERE message_id = ?",
                (attempts, next_at, reason, message_id),
            )
            return "queued"

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

    def __init__(self, outbox: MessageOutbox, adapters: dict, policy, audit=None, dispatcher=None,
                 claim_mode: str = "legacy", stale_after_seconds: int = 300,
                 owner_alert=None):
        self.outbox = outbox
        self.adapters = adapters
        self.policy = policy
        self.audit = audit
        self.dispatcher = dispatcher
        self.owner_alert = owner_alert
        self.send_valve = None  # SendValve — set by build_runtime
        if claim_mode not in {"legacy", "atomic"}:
            raise ValueError(f"unknown claim_mode: {claim_mode}")
        self.claim_mode = claim_mode
        self.stale_after_seconds = stale_after_seconds

    def process_one(self, message: dict, already_claimed: bool = False) -> dict:
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

        if not already_claimed:
            self.outbox.mark_processing(message["message_id"])
        if self.send_valve is not None:   # reputation guard: global tier ceiling
            ok, why = self.send_valve.check_all_outbound(1)
            if not ok:
                from datetime import datetime as _dt, timezone as _tz

                retry_at = (_dt.now(_tz.utc) + _dt.timedelta(minutes=30)).isoformat()
                self.outbox.db.execute(
                    "UPDATE message_outbox SET status='queued', next_attempt_at=?, "
                    "failure_reason=? WHERE message_id=?",
                    (retry_at, f"held: {why}"[:200], message["message_id"]))
                self.outbox.db.commit()
                log.warning("valve.hold mid=%s reason=%s", message["message_id"], why)
                return {"message_id": message["message_id"], "status": "held",
                        "reason": why}
        try:
            result = adapter.send(message["recipient"], message["message_type"], message["payload"])
            self.outbox.mark_sent(message["message_id"], result.get("provider_message_id"))
            self._emit("whatsapp.message.sent" if channel == "whatsapp" else "message.sent", message)
            self._audit("channel.sent", channel, result=str(result))
            return {"message_id": message["message_id"], "status": "sent", "provider_message_id": result.get("provider_message_id")}
        except Exception as exc:  # noqa: BLE001
            from .wa_errors import FAST_DEAD_CATEGORIES, RETRYABLE_CATEGORIES, WhatsAppSendError

            retry_in = None
            dead_now = False
            if isinstance(exc, WhatsAppSendError):
                if exc.category in FAST_DEAD_CATEGORIES:   # auth / bad_recipient
                    dead_now = True
                elif exc.category in RETRYABLE_CATEGORIES:
                    retry_in = exc.retry_after_seconds     # None → default backoff
            final = self.outbox.mark_failed(message["message_id"], f"[{getattr(exc, 'category', 'generic')}] {exc}",
                                            retry_in_seconds=retry_in, dead_now=dead_now)
            if final == "dead" and self.owner_alert is not None:  # OUT-205: dead is never silent
                self.owner_alert(
                    "HIGH",
                    f"[AmanCore] outbox DEAD after {self.outbox.max_attempts} attempts: "
                    f"{message['message_id']} ({str(exc)[:120]})",
                    event_type="outbox.dead", resource=message["message_id"],
                )
            self._emit("message.failed", message)
            self._audit("channel.failed", channel, result=str(exc))
            return {"message_id": message["message_id"], "status": "failed", "reason": str(exc)}

    def drain(self, limit: int = 10) -> list[dict]:
        results = []
        if self.claim_mode == "atomic":
            for msg in self.outbox.claim_batch(limit, self.stale_after_seconds):
                results.append(self.process_one(msg, already_claimed=True))
            return results
        for msg in self.outbox.next_ready(limit):   # legacy: pre-atomic behavior
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
