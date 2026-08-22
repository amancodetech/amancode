# Runbook 04 — Backup

## Symptoms
- Periodic backup is due, or a backup is suspected missing.

## Checks
- `aman-core backup list` → database/business_brain/configs/audit rows exist.
- `aman-core backup verify` → status `verified`, checksum true, integrity ok.

## Safe actions
- `aman-core backup create` — primary copy in `backup/`, secondary copy in `backup/secondary/`, sha256 + size recorded in the `backups` table.
- Schedule via `database.backup` (daily) and `backup.verify` (monthly) jobs.

## Dangerous actions
- Do **NOT** delete backups manually; retention never touches protected records.
- Do **NOT** commit backups to Git (`.gitignore` excludes `backup/`).

## Rollback / Recovery
- A failed backup: inspect the `backups` row status; re-run `backup create`.

## Verification
- `backup verify` → checksum true + integrity `ok` + size reasonable.

## Escalation
- Backup failure twice in a row → create incident `backup_failure` + owner alert.
