# Runbook 01 — Startup

## Symptoms
- AmanCore does not start or behaves unexpectedly.

## Checks
1. `python3 -m amancore.cli health` → RESULT: PASS
2. `python3 -m amancore.cli status` → jobs/channels/business sections present
3. `python3 -m amancore.cli production-check` → expected NOT_READY (production off)

## Safe actions
- Run `StartupService.check()` (via `aman-core status`): config, DB integrity, Business Brain, audit, job queue, backup state, production gate, alert transport.
- Inspect logs under `logs/` (LOG_LEVEL=INFO).
- If a check FAILs, read its detail before touching anything.

## Dangerous actions
- **Do NOT** delete the database, swap files, or enable production.
- **Do NOT** edit `configs/production.yaml` to enable production.

## Rollback / Recovery
- Restore from verified backup: see Runbook 05.

## Verification
- `aman-core health` PASS; `production_send_blocked=true`.

## Escalation
- Any FAIL in `security`, `audit`, or `production_gate` → owner review immediately.
