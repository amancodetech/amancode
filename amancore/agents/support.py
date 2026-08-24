"""Support Agent — bounded customer support for existing customers.

CAN:      read customer/projects/care plans/FAQ, create/update support cases,
          answer operational questions from stored data, request more info, escalate.
CANNOT:   refund, contract change, discount, price change, scope change, binding
          deadline extension, legal advice, Business Brain change, bypass approval.

All replies pass the support response filter; nothing internal ever leaves.
"""

from __future__ import annotations

import json
import re

from ..ids import new_id
from ..support.filter import SupportResponseFilter
from ..support.intent import IntentRouter
from .base import Agent

# CANNOT actions (owner-approval required) — deterministic detection
_SCOPE_CHANGE = re.compile(
    r"(change\s+(the\s+)?scope|extra work|beyond scope|add more|تغيير النطاق|تغير المشروع|tambah kerja)",
    re.IGNORECASE,
)
_DEADLINE_EXTENSION = re.compile(
    r"(extend deadline|more time|postpone|delay|تمديد|تأجيل|perpanjang)",
    re.IGNORECASE,
)
_CONTRACT_CHANGE = re.compile(
    r"(change contract|contract change|renegotiate|تعديل العقد|ubah kontrak)",
    re.IGNORECASE,
)
_DISCOUNT_REQUEST = re.compile(
    r"(discount|cheaper|reduce the price|خصم|potongan|lebih murah)",
    re.IGNORECASE,
)

_SAFE_DEFAULT = "Thank you — our support team has logged your request and will follow up with you."


class SupportAgent(Agent):
    def __init__(
        self,
        brain_store,
        crm,
        cases,
        handover,
        *,
        router=None,
        response_filter=None,
        owner_alert=None,
        support_policy=None,
        audit=None,
        dispatcher=None,
    ):
        super().__init__("support", brain_store, crm=crm, audit=audit, dispatcher=dispatcher)
        self.cases = cases
        self.handover = handover
        self.router = router or IntentRouter()
        self.response_filter = response_filter or SupportResponseFilter()
        self.owner_alert = owner_alert
        self.support_policy = support_policy or {}

    # ------------------------------------------------------------------
    def process_message(self, lead: dict, message: str, customer: dict | None = None) -> dict:
        lead_id = lead["lead_id"]
        corr = new_id()
        category = self.router.classify_category(message)
        critical = self.router.is_critical(message)
        policy = self._policy()
        priority = "CRITICAL" if critical else self.router.priority_for(category, policy)

        # human handoff first (defense in depth — coordinator usually catches it)
        if self._wants_human(message):
            case_id = self._ensure_case(lead, customer, category, priority, message, corr)
            self.handover.request_human(lead_id)
            self._owner_alert("high", f"Support human handoff — lead {lead.get('name', lead_id)} ({category})", corr, event_type="support_handoff", resource=str(lead_id))
            self._emit("support.handoff_requested", {"lead_id": lead_id, "category": category}, corr)
            return {
                "reply": "I'll connect you with our team right away.",
                "category": category, "priority": priority, "case_id": case_id,
                "handoff": True,
            }

        # CRITICAL (security incident / breach / unavailable / serious legal)
        if critical:
            case_id = self._ensure_case(lead, customer, category, "CRITICAL", message, corr)
            self.cases.escalate(case_id, owner="owner")
            self._emit("support.case.escalated", {"case_id": case_id, "priority": "CRITICAL"}, corr)
            self._owner_alert("critical", f"CRITICAL support case {case_id} — {category}", corr, event_type="support_critical", resource=str(case_id))
            self.handover.request_human(lead_id)
            return {
                "reply": "This has been escalated to our security/owner team immediately.",
                "category": category, "priority": "CRITICAL", "case_id": case_id, "escalated": True,
            }

        # Legal / billing / complaint / boundary change → owner escalation (no AI decision)
        if (
            category in ("legal", "billing", "complaint")
            or self._boundary_change(message)
            or _DISCOUNT_REQUEST.search(message)
        ):
            case_id = self._ensure_case(lead, customer, category, priority, message, corr)
            self.cases.escalate(case_id, owner="owner")
            self._emit("support.case.escalated", {"case_id": case_id, "category": category}, corr)
            self._owner_alert("high", f"Support escalation ({category}) — case {case_id}", corr, event_type="support_escalation", resource=str(case_id))
            self.handover.request_human(lead_id)
            reply = {
                "legal": "This matter has been forwarded for legal review by our owner.",
                "billing": "I understand — billing matters are handled by our owner. Your case has been forwarded.",
                "complaint": "I'm sorry about this. Your complaint has been escalated to our owner.",
            }.get(category, _SAFE_DEFAULT)
            return {
                "reply": reply, "category": category, "priority": priority,
                "case_id": case_id, "escalated": True,
            }

        # project status — answer ONLY from stored project data
        if category == "project_status":
            case_id = self._ensure_case(lead, customer, category, priority, message, corr)
            reply = self._project_status_reply(customer)
            if customer is None or not self.crm.get_projects_for_customer(customer["customer_id"]):
                reply = "I'll check with our team about your project status and get back to you."
            return {"reply": reply, "category": category, "priority": priority, "case_id": case_id}

        # feature request / technical support / general — log + request more info
        case_id = self._ensure_case(lead, customer, category, priority, message, corr)
        if category == "feature_request":
            reply = "Thanks! We've noted your request. Could you share more details about what you need?"
        elif category == "technical_support":
            reply = "We're on it. Please share any error message or step that failed so we can help faster."
        else:
            reply = _SAFE_DEFAULT
        return {"reply": reply, "category": category, "priority": priority, "case_id": case_id}

    # ------------------------------------------------------------------
    def _policy(self) -> dict | None:
        """Resolve the support policy; None => UNKNOWN_POLICY => owner escalation."""
        policy = self.support_policy.get("support_policy", {})
        if not policy or not policy.get("response_target"):
            self._emit("support.sla_unknown", {"policy": "missing"})
            self._audit("support.sla_unknown", "policy", result="UNKNOWN_POLICY")
            self._owner_alert("medium", "UNKNOWN_POLICY for support — owner escalation required", None, event_type="unknown_policy")
            return None
        return policy

    def _ensure_case(self, lead, customer, category, priority, message, corr) -> str:
        customer_id = customer["customer_id"] if customer else None
        open_cases = [
            c for c in self.cases.list(lead_id=lead["lead_id"], limit=50)
            if c["category"] == category and c["status"] in ("open", "in_progress", "waiting_customer")
        ]
        if open_cases:
            case = open_cases[0]
            self.cases.update(
                case["case_id"],
                summary=f"{case.get('summary', '')} | {message[:200]}",
                updated_at=case.get("updated_at"),
            )
            self._emit("support.case.updated", {"case_id": case["case_id"]}, corr)
            return case["case_id"]
        case_id = self.cases.create(
            category,
            customer_id=customer_id,
            lead_id=lead["lead_id"],
            conversation_id=self.crm.get_conversation_for_lead(lead["lead_id"]).get("conversation_id")
            if self.crm.get_conversation_for_lead(lead["lead_id"]) else None,
            priority=priority,
            summary=message[:200],
            description=message,
            owner=None,
        )
        self._emit("support.case.created", {"case_id": case_id, "category": category, "priority": priority}, corr)
        self._audit("support.case_created", "case", result=case_id)
        return case_id

    def _project_status_reply(self, customer) -> str:
        if customer is None:
            return _SAFE_DEFAULT
        projects = self.crm.get_projects_for_customer(customer["customer_id"])
        if not projects:
            return _SAFE_DEFAULT
        p = projects[0]
        status = p.get("status") or "active"
        milestones = p.get("milestones")
        timeline = p.get("timeline")
        parts = [f"Your project is currently: {status}."]
        if timeline:
            parts.append(f"Scheduled timeline: {timeline}.")
        if milestones:
            try:
                ms = json.loads(milestones)
                if isinstance(ms, list) and ms:
                    parts.append("Milestones: " + ", ".join(str(m) for m in ms[:5]))
            except (json.JSONDecodeError, TypeError):
                pass
        return " ".join(parts)

    def _boundary_change(self, message: str) -> bool:
        return bool(
            _SCOPE_CHANGE.search(message)
            or _DEADLINE_EXTENSION.search(message)
            or _CONTRACT_CHANGE.search(message)
        )

    def _wants_human(self, message: str) -> bool:
        m = message or ""
        return bool(re.search(r"(human|real person|talk to owner|إنسان|بشري|orang|manusia|owner)", m, re.I))

    def _owner_alert(self, level: str, msg: str, corr, **meta) -> None:
        if self.owner_alert is not None:
            self.owner_alert(level, msg, corr, **meta)

    def safe_reply(self, text: str) -> dict:
        """Filter a reply before it may leave the system (defense in depth)."""
        return self.response_filter.check(text)
