# Policies (Risk / Policy / Approval)

All deterministic — no LLM decisions here.

## Risk Engine

Classifies `event_type` (+ optional `action`) → low/medium/high/critical.

## Policy Engine

`evaluate(brain, event_type, risk_level, action)` → allow / approval_required /
escalate / deny, with `policy_reference` + `reason`.

Rules: final price/discount → approval_required · refund/legal → escalate ·
critical → escalate · high → approval_required · else allow.

## Approval Service

`create_approval_request / approve / reject / edit / expire / cancel`.
Statuses: pending/approved/rejected/edited/expired/cancelled.
Every decision is audited.
