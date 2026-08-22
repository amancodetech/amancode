# Runbook 07 — Job Failure

## Symptoms
- A scheduled job repeatedly fails; dead-letter grows.

## Checks
- `aman-core jobs status` → failed/dead counts.
- `aman-core status` → `jobs.recent_failures` list with error strings.

## Safe actions
- Inspect `error` on the failed job row.
- Re-run the job manually: `aman-core jobs run <job-type>` (idempotency key prevents duplicates).
- Retry policy is config-driven (`configs/scheduler.yaml` → `retry`): exponential backoff, max attempts, dead-letter.

## Dangerous actions
- Do **NOT** clear job rows blindly (evidence).
- Do **NOT** disable a job to silence failures without understanding them.

## Rollback / Recovery
- Fix the underlying cause; `jobs tick` re-enqueues due jobs.

## Verification
- Job completes (`status=completed`) on the next run.

## Escalation
- Repeated failures (config threshold) → incident `job_failure` + owner alert (repeated_errors alert policy).
