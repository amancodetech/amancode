# LOAD-601 / CHAOS-602 — MEASURED REPORT (2026-08-24)

**Machine baseline:** 12 vCPU · 15,838 MB RAM · NVMe · Linux 6.x
**Methodology:** plan §20 — synthetic signed webhooks → isolated in-process
server on :8011, mock LLM at {0.2s, 3s, hard-timeout}, ramp 1→5→10→20
concurrent threads × N msgs each; curve recorded to first degradation.

## Mandatory fields

| Field | fast (0.2s) | slow (3s) | timeout |
|---|---|---|---|
| tested_load | 144 | 144 | 288 |
| p50 webhook latency | 0.964s | 3.854s | 0.756s |
| p95 webhook latency | 4.392s | 9.727s | 4.826s |
| p99 webhook latency | ~5.1s | ~11.9s* | ~5.3s* |
| error_rate | 0% | 0% | 0% |
| max concurrent workers | 43 | 43 | 43 |
| memory trend | 38→91MB flat | flat | flat |
| outbox lag | n/a (sync replies) | n/a | n/a |

\* p99 from the pre-fix 288-msg runs (same build path).
**db_lock_rate:** pre-fix storm measured 272/288 BUSY under 20-way (94%) →
post-fix 0 observed across all profiles.
**No degradation breakpoint hit** within ramp; latency scales with mock-LLM
latency as expected (p50 ≈ 1×/2× profile).

## Escalation signals fired & architectural responses (§20 policy)

1. **BUSY storm (272 errors/run @20-way)** → `Database.execute` bounded
   busy-retry w/ exponential jitter (§20 step ①). Post-fix: zero.
2. **Latent lock-starvation incident (live prod, 50min frozen WAL):** a dead
   request thread held an implicit write txn forever → **autocommit mode**
   (`isolation_level=None`) + explicit `BEGIN IMMEDIATE` in transaction();
   lingering write locks now structurally impossible. `synchronous=NORMAL`
   restores throughput under autocommit.
3. **CRITICAL CONFIG LEAK (caused live Meta WABA ban):** load harness env
   `DATABASE_PATH` was silently ignored by config loader → 1,730 mock replies
   ("رد وهمي مقيس لاختبار الحمل") dispatched via PRODUCTION API to ~989
   numbers in ~3h → permanent WABA disable. Fixes:
   - `cfg.database_path` now honors `DATABASE_PATH` env (root cause)
   - `Database` refuses opening production `aman_core.db` when
     `LOAD_MOCK_LLM`/`AMANCORE_ISOLATED` set (last-line guard, test-proven)
   - inbox sync INSERT made idempotent (`ON CONFLICT DO NOTHING`) — the
     unique index surfaced a real TOCTOU race under concurrency
4. **Thread growth:** capped naturally (~43 incl. per-request), no runaway.

## CHAOS-602 coverage status (failure classes)

| Class | Status |
|---|---|
| Meta 400/401/429/500 | ✅ typed taxonomy tests (test_wa302) + retry policy |
| AI timeout/malformed/unavailable | ✅ fallback deterministic (mock timeout profile above + unit stubs) |
| DB locked | ✅ busy-retry + this report's storm→fix cycle |
| worker crash / lease expiry | ✅ cooperative-cancel + zombie exclusion (test_jobs304) |
| server restart durability | ✅ WAL reopen tests; live restarts ×N today health 200 |
| disk-full backup | partial — raise-path covered (BAK-103); ENOSPC injection pending |
| **partial-migration resume** | ✅ ensure_columns/indexes idempotent ×2 (tests) |
| duplicate webhook flood | ✅ atomic claims exactly-once (20/20) + idempotent sync insert |

## Verdict for G6
Load/failure evidence complete EXCEPT: ENOSPC injection test + a scheduled
re-measure on quiet-hours production traffic. Cost-governor protections
(TEST-COST-01..05) already green (COST-402).
