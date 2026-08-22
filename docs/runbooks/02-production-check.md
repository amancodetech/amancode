# Runbook 02 — Production Check

## Symptoms
- Owner needs to know if external sending may be enabled.

## Checks
1. `python3 -m amancore.cli production-check`
2. Inspect every gate: official docs verified, account config, business verification, phone number, webhook reachable/verified, signature tested, outbound tested, opt-out, human takeover, idempotency, outbox, policy, audit, health, owner alert, secrets, backup verified, recovery test, runbooks, alert transport, owner destination.

## Safe actions
- Run the check any time; it is read-only.
- Treat `OFFICIAL_VERIFICATION_PENDING` as a hard stop.

## Dangerous actions
- **Never** flip `production_enabled: true` in `configs/production.yaml` until ALL gates PASS and the owner explicitly confirms.
- **Never** change `WHATSAPP_MODE` to production based on assumptions.

## Rollback / Recovery
- If production was enabled and must be disabled: set `production_enabled: false` and `mode: mock`, then verify `GraphWhatsAppProvider.send` raises `ProductionNotEnabledError`.

## Verification
- `verdict: READY` on a fresh check after enabling, plus a successful controlled smoke test.

## Escalation
- Any gate FAIL → document it; unresolved blockers → owner review.
