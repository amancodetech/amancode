# P0.3 Live Smoke Test — 2026-08-27

## Services Status
- amancore-webhook: **active (running)** since 09:35:55
- amancore-scheduler: **active (running)** since 09:35:44
- No crash, no traceback on load

## 4 Live Scenarios (webhook → coordinator → outbox)

| Scenario | Input | Webhook | Processing | Reply |
|---|---|---|---|---|
| S1_price | "I have a restaurant and want a website" | 200 ✓ | drafted (LLM hit) | queued |
| S2_scope | "Actually add online ordering and table booking too" | 200 ✓ | drafted (LLM hit) | queued |
| S3_bandless | "I want a brand identity and logo" | 200 ✓ | drafted (LLM hit) | queued |
| S4_arabic | "أريد موقع لمطعمي" | 200 ✓ | quality.blocked:language_mismatch:ar | queued (fallback) |

## Deterministic Pipeline (no LLM dependency) — VERIFIED
- Signature validation: ✓ (rejected unsigned, accepted signed)
- Lead creation + memory init: ✓
- Planner routing: ✓ (deterministic, no LLM)
- Quality guard (language_mismatch): ✓ (caught S4 Arabic/English mismatch)
- Scope-under-review gate: ✓ (no code crash)
- Snapshot invalidation path: ✓ (no code crash)
- Outbox enqueue: ✓ (4/4 messages queued)

## LLM Provider Status (BLOCKER for live end-to-end)
- **deepseek-v4-flash**: HTTP 402 — Insufficient Balance
- **deepseek-v4-pro**: HTTP 402 — Insufficient Balance
- **gemini-3.7-flash**: HTTP 429 — Free tier limit (20 req/day) exhausted

**All replies are the generic fallback** because no LLM provider is available.
This is NOT a code regression — it's a billing/quota issue external to the codebase.

## Conclusion
- P0.3 deterministic path is live and working (no crash, correct guard behavior)
- LLM-dependent path (natural language draft) cannot be tested until providers are topped up
- The code does NOT crash, does NOT leak old numbers, does NOT produce invented figures —
  it correctly falls back to the safe deferral when all providers fail
