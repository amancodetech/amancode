# Runbook 06 — Webhook Failure

## Symptoms
- WhatsApp webhook returns errors; signature verification fails; events stop arriving.

## Checks
- `aman-core status` → `channels.webhook_failures_today` growing.
- Monitor `events` where `event_type = 'whatsapp.webhook.failed'`.
- Verify `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` in `.env`.

## Safe actions
- Verify token match; confirm HTTPS reachability of the webhook URL; confirm Meta app settings.
- In mock mode: webhook failures are simulated — expected.

## Dangerous actions
- Do **NOT** disable signature validation to "fix" failures.
- Do **NOT** switch to production to test the webhook.

## Rollback / Recovery
- Re-run the verification handshake; fix env values; re-test with a mock payload.

## Verification
- `whatsapp.webhook.verified` event appears; inbound events processed.

## Escalation
- Repeated failures in production → incident `webhook_failure` + owner alert.
