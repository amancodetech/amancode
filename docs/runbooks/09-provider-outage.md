# Runbook 09 — Provider Outage

## Symptoms
- AI provider errors (`usage_records.status='error'`), message provider failures, latency spikes.

## Checks
- `aman-core status` → `ai.failures_total`, `avg_latency_ms`, `channels.outbox` dead/failed counts.
- `usage_records` for provider/model error patterns.

## Safe actions
- The Model Router fallback chain (Pro → Gemini → Flash) handles single-provider outages automatically.
- Outbox retry/backoff + dead-letter contain message-send failures.
- Alert policies: `api_failures` (threshold in configs/alerts.yaml).

## Dangerous actions
- Do **NOT** lower the model for high-risk tasks just to reduce cost during an outage.

## Rollback / Recovery
- Verify provider status; when restored, outbox retries resume automatically.

## Verification
- Failure rate returns to normal; jobs complete; no dead-letter growth.

## Escalation
- Sustained outage → incident `provider_failure` + owner alert.
