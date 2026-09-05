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
    #: dims that may be explicitly deferred by the customer (D4). Shape and
    #: scale are NEVER deferrable — "don't know" there routes to a choices
    #: question (D7), never to an estimate.
    GATEB_DEFERRABLE = frozenset({"budget", "authority", "languages",
                                  "integrations", "payments"})

    @staticmethod
    def gate_b_ready(policy, category: str | None, facts: dict,
                     unknown_accepted: list | None = None,
                     missing_out: list | None = None) -> bool:
        """D2-APPROVED: responsible T2 estimate needs shape + scale +
        one connect dimension + authority/budget (or explicit deferral).

        unknown_accepted (D4) counts only for deferrable dims. When
        missing_out is given it is filled with gap labels for the
        auto-suggest step (D2-D): shape | scale | connect |
        authority_or_budget.
        """
        facts = facts or {}
        accepted = {k for k in (unknown_accepted or [])
                    if k in QuoteFlow.GATEB_DEFERRABLE}

        def known(field: str) -> bool:
            try:
                if policy.field_known(field, facts):
                    return True
            except Exception:  # noqa: BLE001 — policy must never break gate
                pass
            for key in (policy.data.get("field_satisfied_by", {}).get(field, ())
                        if policy is not None else ()):
                if key in accepted:
                    return True
            return False

        def flag(key: str) -> bool:
            return bool(facts.get(key)) or key in accepted

        missing: list[str] = []
        if not category:
            missing.append("category")
        if not known("key_features"):
            missing.append("shape")
        if not (known("timeline") or known("scale")):
            missing.append("scale")
        connect = (known("integrations") or known("languages")
                   or flag("payments") or flag("payment_gateways")
                   or flag("gateways"))
        if not connect:
            missing.append("connect")
        if not (known("authority") or known("budget_band")):
            missing.append("authority_or_budget")
        if missing_out is not None:
            missing_out.extend(missing)
        return not missing

    # ---- T2 estimate -----------------------------------------------------
    def estimate(self, lead: dict, category: str,
                 hours_override: int | None = None,
                 scope_addons: list[str] | None = None,
                 facts: dict | None = None,
                 small: bool = False) -> dict | None:
        from ..pricing import fx as _fx
        engine = PricingEngine(self.brain_store)
        market, currency = _fx.resolve_market(
            (lead or {}).get("language"), lead)
        service_id = self._service_id(category)
        brain = self.brain_store.current()[1] if self.brain_store else {}
        if hours_override is not None:
            hours = hours_override
        elif facts:
            hours = registry.calculate_dynamic_hours(brain, service_id, facts, small=small)
        else:
            hours = registry.base_hours(brain, service_id) or 0
        if not hours or not service_id:
            return None
        risk = "low" if hours <= 10 else "medium"
        result = engine.price({
            "service": service_id,
            "estimated_hours": hours,
            "market": market,
            "risk_level": risk,
            "add_ons": scope_addons or [],
        })
        # Engine figures are USD-magnitude (USD is the fixed base). Arabic
        # market stays USD; Indonesian market converts at the Brain-pinned
        # daily rate — frozen per correspondence (rate + date stored below).
        low = _round100(result["negotiation_floor"])
        high = _round100(result["target_price"])
        fx_rate: int | None = None
        fx_date: str | None = None
        usd_low, usd_high = low, high
        if currency == "IDR":
            fx_rate, fx_date = _fx.get_usd_idr_rate(brain)
            low = _fx.usd_to_idr(low, fx_rate)
            high = _fx.usd_to_idr(high, fx_rate)
            result = dict(result, currency="IDR",
                          usd_base_low=usd_low, usd_base_high=usd_high,
                          fx_rate=fx_rate, fx_date=fx_date)
        else:
            currency = "USD"
        return {
            "service_id": service_id,
            "low": low, "high": high,
            "currency": currency,
            "market": market,
            "usd_base_low": usd_low, "usd_base_high": usd_high,
            "fx_rate": fx_rate, "fx_date": fx_date,
            "pricing_result": result,
        }

    def _service_id(self, category: str) -> str | None:
        brain = self.brain_store.current()[1] if self.brain_store else {}
        return registry.service_for_category(brain, category)

    # ---- owner approval --------------------------------------------------
    def request_owner_approval(self, lead: dict, estimate: dict,
                               corr: str | None = None,
                               scope_fingerprint: str | None = None,
                               ai_breakdown: dict | None = None,
                               unknown_dimensions: list | None = None,
                               hours_source: str | None = None) -> str:
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
            "market": estimate.get("market"),
            # FX freeze: the rate of THIS correspondence day. T3/snapshots
            # replay these stored figures; later Brain rate updates never
            # rewrite them. USD base kept for audit.
            "usd_base_high": estimate.get("usd_base_high"),
            "usd_base_low": estimate.get("usd_base_low"),
            "fx_rate": estimate.get("fx_rate"),
            "fx_date": estimate.get("fx_date"),
            "pricing_result": estimate["pricing_result"],
            "scope_fingerprint": scope_fingerprint,
            "ai_breakdown": ai_breakdown,
            # D2/D9: unknowns + hours provenance travel with the approval so
            # the owner sees what the figures do NOT yet know.
            "unknown_dimensions": list(unknown_dimensions or []),
            "hours_source": hours_source or ("ai" if ai_breakdown else "deterministic"),
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
            cname = lead.get("name") or lead["lead_id"]
            hours_val = estimate.get("pricing_result", {}).get("estimated_hours", 0)
            bd_text = ""
            if ai_breakdown:
                summary = ai_breakdown.get("summary", "")
                summary_line = f"• تحليل الذكاء الاصطناعي: {summary}\n" if summary else ""
                fe = ai_breakdown.get("frontend", 0)
                be = ai_breakdown.get("backend", 0)
                integ = ai_breakdown.get("integrations", 0)
                qa = ai_breakdown.get("qa_deploy", 0)
                bd_text = (f"{summary_line}"
                           f"• تفصيل الساعات ({hours_val:g}س): واجهات: {fe:g}س | خوادم: {be:g}س | تكاملات: {integ:g}س | نشر واختبار: {qa:g}س\n")
            elif hours_val:
                bd_text = f"• ساعات العمل المقدرة: {hours_val:g} ساعة\n"
            from ..pricing import fx as _fxa
            _high_txt = _fxa.format_idr(estimate["high"]) \
                if estimate["currency"] == "IDR" \
                else f"{estimate['high']:g} {estimate['currency']}"
            _low_txt = _fxa.format_idr(estimate["low"]) \
                if estimate["currency"] == "IDR" \
                else f"{estimate['low']:g} {estimate['currency']}"
            _fx_txt = ""
            if estimate.get("fx_rate"):
                _fx_txt = (f"• 💱 الصرف المجمّد لهذه المراسلة: 1 USD = "
                           f"{estimate['fx_rate']:,} IDR "
                           f"(بتاريخ {estimate.get('fx_date')}، "
                           f"الأساس ${estimate.get('usd_base_high'):g})\n")
            self.owner_alert(
                "high",
                f"🔔 طلب اعتماد سعر رسمي للمشروع:\n"
                f"• العميل: {cname}\n"
                f"• الخدمة: {estimate['service_id']}\n"
                f"{bd_text}"
                f"• 🎯 السعر المستهدف المقترح: {_high_txt}\n"
                f"• 🛡️ أدنى حد مسموح للتفاوض: {_low_txt}\n"
                f"{_fx_txt}"
                f"──────────\n"
                f"⚡ للاعتماد بالسعر المقترح ({_high_txt}): /qapprove {approval_id[:8]}\n"
                f"✏️ أو حدد سعراً مخصصاً: /qapprove {approval_id[:8]} <السعر>",
                corr, event_type="quote_approval", resource=str(lead["lead_id"]))
        return approval_id

    # ---- T3 finalize -------------------------------------------------------
    def finalize(self, approval_id: str, approved_by: str,
                 price_override: float | None = None) -> str:
        row = self.approvals.get(approval_id)
        if row is None or row["status"] != "pending":
            raise ValueError(f"approval {approval_id} not pending")
        payload = json.loads(row["payload"] or "{}")
        self.approvals.approve(approval_id, approved_by)
        version, _data = self.brain_store.current()
        expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        final_price = float(price_override) if price_override is not None else float(payload["proposed_price"])
        snapshot_id = self.snapshots.create(
            opportunity_id=payload["opportunity_id"],
            pricing_result=payload.get("pricing_result") or {},
            approved_price=final_price,
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
                    result=f"{final_price:g} {payload['currency']}")
        self._emit("quote.snapshot_created", {"snapshot_id": snapshot_id,
                                              "approval_id": approval_id})
        return snapshot_id

    def pending(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT approval_id, reason, payload, requested_at FROM approvals "
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
