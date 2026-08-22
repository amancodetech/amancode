"""Incident Service — incident model + critical response flow.

CRITICAL: Detect → Block dangerous actions → Owner Alert → Create Incident →
Preserve evidence → Mitigate → Resolve → Post-incident note.
Evidence is NEVER deleted.
"""

from __future__ import annotations

from ..ids import new_id, utcnow
from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.incidents")

INCIDENT_TYPES = (
    "channel_failure", "webhook_failure", "database_failure", "job_failure",
    "security_incident", "backup_failure", "provider_failure", "ai_failure",
    "data_quality", "production_blocked",
)
STATUSES = ("open", "investigating", "mitigated", "resolved", "closed")


class IncidentService:
    def __init__(self, db: Database, owner_alert=None, dispatcher=None):
        self.db = db
        self.owner_alert = owner_alert
        self.dispatcher = dispatcher  # ops.alerts.AlertDispatcher

    def create(self, type_: str, severity: str, component: str = "",
               description: str = "", evidence: dict | None = None,
               owner: str | None = None) -> str:
        if type_ not in INCIDENT_TYPES:
            raise ValueError(f"invalid incident type: {type_}")
        incident_id = new_id()
        now = utcnow()
        import json

        self.db.execute(
            "INSERT INTO incidents (incident_id, type, severity, component, status, "
            " description, evidence, owner, detected_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)",
            (incident_id, type_, severity, component, description,
             json.dumps(evidence or {}, ensure_ascii=False), owner, now, now, now),
        )
        self.db.commit()
        return incident_id

    def get(self, incident_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return dict(row) if row else None

    def list(self, status: str | None = None, severity: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM incidents WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, tuple(params)).fetchall()]

    def update(self, incident_id: str, **fields) -> None:
        if self.get(incident_id) is None:
            raise ValueError(f"incident not found: {incident_id}")
        sets = [f"{k} = ?" for k in fields]
        self.db.execute(
            f"UPDATE incidents SET {', '.join(sets)}, updated_at = ? WHERE incident_id = ?",
            (*fields.values(), utcnow(), incident_id),
        )
        self.db.commit()

    def set_status(self, incident_id: str, status: str, note: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid incident status: {status}")
        fields = {"status": status}
        if status in ("resolved", "closed") and not self.get(incident_id).get("resolved_at"):
            fields["resolved_at"] = utcnow()
        if note:
            fields["action_taken"] = f"{self.get(incident_id).get('action_taken', '')}\n{note}".strip()
        self.update(incident_id, **fields)

    def handle_critical(self, type_: str, description: str, evidence: dict | None = None,
                        component: str = "", block_action=None) -> str:
        """CRITICAL flow: block dangerous actions → owner alert → incident."""
        if block_action is not None:
            try:
                block_action()
            except Exception as exc:  # noqa: BLE001
                log.error("incident block action failed: %s", exc)
        if self.dispatcher is not None:
            self.dispatcher.dispatch(
                severity="CRITICAL", category="incident", title=f"CRITICAL: {type_}",
                summary=description, evidence=evidence or {},
                action_required="immediate owner response", related_entity=type_,
            )
        elif self.owner_alert is not None:
            self.owner_alert("critical", f"CRITICAL INCIDENT {type_}: {description}", None)
        incident_id = self.create(type_, "CRITICAL", component=component,
                                  description=description, evidence=evidence, owner="owner")
        log.warning("critical incident %s (%s): %s", incident_id, type_, description)
        return incident_id
