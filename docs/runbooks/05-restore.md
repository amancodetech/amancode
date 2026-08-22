# Runbook 05 — Restore

## Symptoms
- Database corruption, data loss, or the need to roll back state.

## Procedure (production DB is NEVER restored automatically)
1. **Stop** the runtime (stop scheduler/workers).
2. **Preserve** the damaged DB (copy to a quarantine path; never delete evidence).
3. Select a **verified** backup: `aman-core backup list` + `backup verify`.
4. Restore to a **temporary** path first: `RecoveryService.restore_to_temp(backup_id)` — integrity check runs automatically.
5. Integrity check on the temp DB (`PRAGMA integrity_check` → ok).
6. Health check on the temp DB (tables present, core queries work).
7. **Swap** the DB (replace `storage/aman_core.db` with the restored file) — explicit human command only.
8. Restart the runtime.
9. Smoke test: `aman-core health` PASS + a controlled inbound test.
10. Audit the incident (create `database_failure` incident, log evidence).

## Safe actions
- `aman-core recovery-test`-style restore to temp — always safe.

## Dangerous actions
- **Never** run restore against the production path automatically.
- **Never** delete the damaged DB.

## Rollback / Recovery
- If the restored DB fails health, restore another backup or revert the swap.

## Verification
- Health PASS after swap + a successful read/write smoke.

## Escalation
- Restore failure → incident + owner alert immediately.
