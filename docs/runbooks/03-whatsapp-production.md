# Runbook 03 — WhatsApp Production Enablement

## Symptoms
- Owner wants to go live on WhatsApp.

## Checks (ALL required — no guessing)
1. Official Meta / WhatsApp Business Platform documentation verified (current API version, endpoints, webhook verification, X-Hub-Signature-256, permissions, templates, messaging policy, rate limits).
2. Account configuration + Business Verification (if currently required).
3. Phone number configured.
4. Webhook HTTPS reachable + verification successful (hub.challenge).
5. Signature validation tested.
6. Outbound test successful (controlled, test number only).
7. Template requirements satisfied (where applicable).
8. Opt-out tested, human takeover tested, idempotency tested, outbox tested, policy tested, audit tested.
9. Health check PASS.
10. Owner Alert transport configured (not log fallback).
11. Secrets configured in `.env`.
12. Backup verified + recovery test passed.
13. Production smoke tests PASS.
14. Owner explicit confirmation.

## Safe actions
- Fill `.env` secrets; run `aman-core owner-alert-test`; run smoke tests in mock first.

## Dangerous actions
- Do **NOT** enable production if any item is UNKNOWN / VERIFICATION REQUIRED.
- Do **NOT** use WAHA, instagrapi, browser automation, or unofficial APIs — ever.

## Rollback / Recovery
- `production_enabled: false` + `mode: mock` at any time; the gate blocks sends immediately.

## Verification
- `aman-core production-check` → READY; one real outbound test to a test number; webhook round-trip.

## Escalation
- If official verification fails or is unreachable → keep `WHATSAPP_MODE=mock`; report the blocker.
