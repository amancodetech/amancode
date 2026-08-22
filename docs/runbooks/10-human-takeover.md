# Runbook 10 — Human Takeover

## Symptoms
- A customer requests a human, or a conversation requires human attention.

## Checks
- `HandoverService.get_mode(lead_id)` — one of AI_ACTIVE / HUMAN_REQUESTED / HUMAN_ACTIVE / AI_RESUMED / CLOSED.

## Safe actions
- `request_human` → HUMAN_REQUESTED + owner alert + handoff event.
- `activate_human` → HUMAN_ACTIVE: **AI stops sending automatically** (enforced in the coordinator + outbox).
- Owner replies; `resume_ai` → AI_RESUMED before AI may send again.

## Dangerous actions
- Do **NOT** override the mode to AI_ACTIVE while a human is mid-conversation.
- Do **NOT** let AI reply during HUMAN_ACTIVE (verified by tests).

## Rollback / Recovery
- If AI wrongly sent during HUMAN_ACTIVE → create incident, audit, and fix the mode.

## Verification
- Smoke test `human_takeover` PASS: incoming message is logged in CRM but generates no AI outbound.

## Escalation
- Mode stuck or AI sends during human → incident `production_blocked`-style + owner alert.
