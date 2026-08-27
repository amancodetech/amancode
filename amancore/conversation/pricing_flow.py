"""QuoteFlow — pricing conversation tiers T0–T3 (P0-3).

    T0  no scope            -> no numbers (coordinator deferral, unchanged)
    T1  public bands        -> only when owner fills brain.price_bands_public
    T2  Gate-B scope known  -> deterministic indicative estimate + owner
                               approval request (final_price)
    T3  approval granted    -> frozen snapshot; coordinator already reads it

Deterministic authority is untouched: the LLM may only convey figures that
arrive inside its draft payload; approvals stay owner-only.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..pricing.engine import PricingEngine
from ..pricing import registry
from ..services.approvals import ApprovalService
from ..services.events import CanonicalEvent
from ..ids import new_id, utcnow


def _round100(x: float) -> float:
    return float(round(x / 100.0) * 100)


class QuoteFlow:
    def __init__(self, db, crm, brain_store, snapshot_store, dispatcher=None,
                 owner_alert=None, audit=None):
        self.db = db
        self.crm = crm
        self.brain_store = brain_store
        self.snapshots = snapshot_store
        self.approvals = ApprovalService(db, audit=audit)
        self.dispatcher = dispatcher
        self.owner_alert = owner_alert
        self.audit = audit

    # ---- gates ---------------------------------------------------------
    @staticmethod
    def gate_b_ready(policy, category: str | None, facts: dict) -> bool:
        """Enough scope for a responsible T2 estimate."""
        if not category:
            return False
        if not policy.field_known("key_features", facts):
            return False
        return policy.field_known("timeline", facts) or policy.field_known("scale", facts)

    # ---- T2 estimate -----------------------------------------------------
    def estimate(self, lead: dict, category: str,
                 hours_override: int | None = None,
                 scope_addons: list[str] | None = None) -> dict | None:
        engine = PricingEngine(self.brain_store)
        market = "gcc" if str(lead.get("language") or "").startswith("ar") \
            else (lead.get("market") or "indonesia")
        service_id = self._service_id(category)
        brain = self.brain_store.current()[1] if self.brain_store else {}
        hours = hours_override or registry.base_hours(brain, service_id) or 0
        if not hours or not service_id:
            return None
        risk = "low" if (hours_override or 0) <= 10 else "medium"
        result = engine.price({
            "service": service_id,
            "estimated_hours": hours,
            "market": market,
            "risk_level": risk,
            "add_ons": scope_addons or [],
        })
        low = _round100(result["negotiation_floor"])
        high = _round100(result["target_price"])
        return {
            "service_id": service_id,
            "low": low, "high": high,
            "currency": result.get("currency", "USD"),
            "market": market,
            "pricing_result": result,
        }

    def _service_id(self, category: str) -> str | None:
        brain = self.brain_store.current()[1] if self.brain_store else {}
        return registry.service_for_category(brain, category)

    # ---- owner approval --------------------------------------------------
    def request_owner_approval(self, lead: dict, estimate: dict,
                               corr: str | None = None,
                               scope_fingerprint: str | None = None) -> str:
        opp = self.crm.get_opportunity_for_lead(lead["lead_id"])
        opportunity_id = opp["opportunity_id"] if opp else None
        if not opportunity_id:
            service = estimate["service_id"]
            opportunity_id = self.crm.create_opportunity(
                lead["lead_id"], service,
                offer_id=service, stage="offer_recommended",
                scope_summary="auto: price intent with sufficient scope")
        payload = {
            "lead_id": lead["lead_id"],
            "opportunity_id": opportunity_id,
            "service_id": estimate["service_id"],
            "proposed_price": estimate["high"],
            "minimum_price": estimate["low"],
            "currency": estimate["currency"],
            "pricing_result": estimate["pricing_result"],
            "scope_fingerprint": scope_fingerprint,
        }
        approval_id = self.approvals.create_approval_request(
            type_="final_price",
            requested_by="conversation_engine",
            risk_level="high",
            reason=(f"Indicative quote {estimate['low']:g}–{estimate['high']:g} "
                    f"{estimate['currency']} for lead {lead.get('name') or lead['lead_id']}"),
            payload=payload,
            policy_reference="brain.decision_policies.price_approval=owner_only",
        )
        self._emit("quote.approval_pending", {
            "approval_id": approval_id, "lead_id": lead["lead_id"],
            "opportunity_id": opportunity_id}, corr)
        if self.owner_alert:
            self.owner_alert(
                "high",
                f"💰 موافقة عرض مطلوبة ({estimate['low']:g}–{estimate['high']:g} "
                f"{estimate['currency']}) — اعتمدها بـ /qapprove {approval_id[:12]}",
                corr, event_type="quote_approval", resource=str(lead["lead_id"]))
        return approval_id

    # ---- T3 finalize -------------------------------------------------------
    def finalize(self, approval_id: str, approved_by: str) -> str:
        row = self.approvals.get(approval_id)
        if row is None or row["status"] != "pending":
            raise ValueError(f"approval {approval_id} not pending")
        payload = json.loads(row["payload"] or "{}")
        self.approvals.approve(approval_id, approved_by)
        version, _data = self.brain_store.current()
        expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        snapshot_id = self.snapshots.create(
            opportunity_id=payload["opportunity_id"],
            pricing_result=payload.get("pricing_result") or {},
            approved_price=float(payload["proposed_price"]),
            approved_by=approved_by,
            business_brain_version=version,
            expiration_at=expires,
            scope_fingerprint=payload.get("scope_fingerprint"),
        )
        try:
            self.crm.update_opportunity(payload["opportunity_id"], stage="offer_ready")
        except Exception:  # noqa: BLE001 — stage vocabulary stays soft
            pass
        self._audit("quote.snapshot_created", snapshot_id,
                    result=f"{payload['proposed_price']:g} {payload['currency']}")
        self._emit("quote.snapshot_created", {"snapshot_id": snapshot_id,
                                              "approval_id": approval_id})
        return snapshot_id

    def pending(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT approval_id, reason, requested_at FROM approvals "
            "WHERE type='final_price' AND status='pending' ORDER BY requested_at").fetchall()
        return [dict(r) for r in rows]

    # ---- infra -------------------------------------------------------------
    def _emit(self, event_type: str, payload: dict, correlation_id: str | None = None):
        if self.dispatcher is None:
            return
        self.dispatcher.publish(CanonicalEvent(
            event_id=new_id(), event_type=event_type, timestamp=utcnow(),
            source="quote_flow", actor_type="system",
            correlation_id=correlation_id, payload=payload))

    def _audit(self, action: str, resource: str, **fields):
        if self.audit is not None:
            self.audit.record(action=action, resource=resource, **fields)
