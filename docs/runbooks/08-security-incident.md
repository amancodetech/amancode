# Runbook 08 — Security Incident

## Symptoms
- Suspicious access, secret leak suspicion, unexpected data access, malware signs.

## Checks
- Audit trail: `aman-core audit recent`.
- `.env` permissions (`600`), not in Git, no secret in logs/reports/alerts/DB.
- Recent alerts and incidents.

## Safe actions
- Immediately: **block dangerous actions** (disable external sends — production gate already does this).
- Create incident `security_incident` (CRITICAL) via `IncidentService.handle_critical` → owner alert fires automatically.
- **Preserve evidence** (logs, audit, DB snapshot) — never delete.

## Dangerous actions
- Do **NOT** rotate/delete evidence.
- Do **NOT** silently fix and forget — document the post-incident note.

## Rollback / Recovery
- Rotate any leaked credentials in `.env`; re-verify `.gitignore` excludes `.env`.

## Verification
- No secrets in git history; audit entries intact; incident resolved + closed with notes.

## Escalation
- Always owner + follow legal/safety requirements (owner decides).
