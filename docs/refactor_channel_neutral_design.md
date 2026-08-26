# Channel-Neutralization Refactor — Approved Design (2026-08-26)

> Baseline: 572/572 PASS @ `dee6e75` (+8 uncommitted inbox files, preserved).
> Rules honored: no rewrite · SQLite stays · unittest only · official APIs · owner approvals intact.

## D1. Canonical Transport Model (`channels/canonical.py`)
- `InboundMessage`: channel · external_message_id · external_user_id · external_conversation_id=None · text · name · message_type · timestamp · reply_to_external_message_id · metadata.
- `ChannelCapabilities` (frozen): text,image,audio,video,document,sticker,template,reaction,read_receipt,reply_context + `TEXT_ONLY` default.
- Built from CanonicalEvent (adapter owns provider parsing; one parse total).

## D2. Adapter Contract (`channels/contract.py`) — every method has a consumer
| Method | Consumer |
|---|---|
| send / receive_webhook / verify_webhook | existing |
| verify_signature (fail-closed: base raises) | coordinator generic signature gate |
| capabilities() | OutboxWorker pre-send fast-fail + inbox guards |
| normalize_recipient(raw) | coordinator/outbox recipient prep (WA=E164 digits) |
| classify_error(exc)->(category,retry_after) | OutboxWorker retry logic (removes provider import) |

Provider-specific code remains ONLY in: `channels/whatsapp.py`, `channels/wa_errors.py`, composition roots (`webhook_server.build_runtime`, scheduler adapter factory), WA ops smoke.

## D3. Event Vocabulary (generic)
`message.received|sent|failed|delivered|read|reaction` + `webhook.verified|webhook.failed`; channel carried in `CanonicalEvent.channel`. `EVENT_TYPES` purged of `whatsapp.*`.
Event system WIRED for real: persistence subscriber writes every published event to `events` table (was decorative/empty).

## D4. Identity Architecture
New table:
```
platform_identities(identity_id PK, lead_id FK->leads CASCADE, channel,
external_user_id, external_username, is_primary, verified, created_at, updated_at,
UNIQUE(channel, external_user_id))
```
- Idempotent backfill: one identity row per lead with non-empty contact_whatsapp.
- CRM: `find_lead_by_identity(channel, ext)` (exact match), `add_lead_identity`, legacy `find_lead_by_whatsapp` = alias over generic resolver with contact_whatsapp fallback (transition bridge).
- Resolution modes: exact / none(create) / manual merge = OWNER ACTION ONLY (never automatic).

## D5. Conversations — evidence-based decision: LEAD-SCOPED (option A) + additive `external_thread_id`
Evidence: sales state machine + discovery playbook assume ONE continuous relationship per lead; message-level threads are already identity-scoped (per channel+external_user_id) so unrelated external threads never mix at transcript level. Splitting memory per channel would fork sales state. Revisit only when a second real customer channel ships.

## D6. Schema Decoupling (idempotent migration in `storage/db.py`)
- `channel_messages`: wa_id→**external_user_id**, wa_message_id→**external_message_id**, quoted_wamid→**quoted_external_message_id** (SQLite RENAME COLUMN inside transaction; indexes dropped/recreated; unique becomes (channel, external_message_id) partial).
- `message_outbox` drift fixed: claimed_at/claim_token/initiation/delivery_status added to schema.sql (authoritative).
- Fresh-DB and upgraded-live-DB converge (migration no-ops on fresh).
- Legacy `leads.contact_whatsapp` retained (display/console/fallback); core lookups go through identities.

## D7. Coordinator (generic)
`handle_inbound(adapter_or_channel, body, headers, raw_body)`; dispatch on generic event types; `_process_inbound(InboundMessage)`:
identity→consent→memory(channel)→handover(channel)→optout→human-intent→intent-router→price→sales; history/governor/recipient all keyed `(channel, external_user_id)`. Recipient normalization behind adapter. System prompts channel-neutral ("AmanCode assistant") + CHANNEL line. Reply drafting via ModelRouter(task=ROUTINE) — removes hard-coded deepseek-v4-flash bypass.

## D8. Outbox + ChannelRouter
`channels/router.py: ChannelRouter` (registry lookup + capabilities). Worker accepts dict-or-router; pre-send capability fast-fail (dead, reason=capability_unsupported — no provider call); errors classified via `adapter.classify_error`; single event vocabulary emitted. Atomic claims/retries/uncertain/dead-letter UNTOUCHED.

## D9. Idempotency
Inbound keys minted INSIDE adapters as `{short}:{provider_id}` (wa:, tg:, …) — cross-channel collision impossible by prefix; existing stored keys remain valid (no replay risk). Scheduler slot race + website dedup unchanged (already guarded); inbox double-click keeps uuid keys (owner-initiated, audit-backed).

## D10. Governance split
- GLOBAL (unchanged): ConsentGate(opt-out/consent), ExternalResponseFilter, audit, approvals, human takeover.
- CHANNEL: SendValve gains `channel` param (counts per-channel; tiers/auto-cap per channel config w/ legacy defaults). Single shared runtime valve now also used by inbox initiation (fixes reservation-split bug). TemplateLock stays a WhatsApp Cloud API mechanism (provider requirement) invoked only for whatsapp initiations.
- CostGovernor: keys `{channel}:{ext}`; NEW persistent daily counters `cost_counters(day,key,calls,tokens)` (survives restarts, multi-process UPSERT); hourly windows stay in-process (documented limitation).

## D11. Follow-ups (deterministic, no AI channel-spam)
Recipient = first available identity by configured preference list (`compliance.followup_channel_preference`, default ["whatsapp"]). Template policy resolved PER CHANNEL; channels without an approved initiation policy are skipped+logged. Valve reservation per target channel.

## D12. Scheduler `_drain`
No more ad-hoc WhatsAppAdapter + `_AllowPolicy` bypass: shared factory builds the same adapter registry + real ChannelPolicyEngine from configs (policy parity with runtime).

## D13. Health / Monitoring / Analytics
Per-channel health checks (`channel_config:<ch>`, `channel_webhook:<ch>` via adapter.verify_webhook); monitoring aggregates generic message events GROUP BY channel; daily report counts generic received events. No useful check deleted.

## D14. Owner consoles stay OWNER-channels
Telegram console + web inbox keep their roles; internal lookups switch to generic helpers; inbox HTTP keeps `wa_id` param names for UI stability (server maps to canonical ids). Console dead code removed (`_remember` stub, broken `/chat` branch).

## D15. Webhook transport routing
Path registry `{"<base>/webhook/<channel>": adapter}`; GET challenge + POST intake resolve adapter by path; coordinator receives (channel, body…). Meta params stay adapter-side.

## D16. Enforcement (architecture tests, always-on)
1. Domain dirs (crm/sales/support/pricing/analytics/insights/services/compliance/agents/business_brain/routing/skills/functions/ops minus smoke) must NOT import provider channel modules nor contain `wa_id|wamid|contact_whatsapp|'whatsapp'` literals (whitelist documented in test).
2. EVENT_TYPES free of provider prefixes.
3. Seventh-Channel Test: FakeAdapter end-to-end (webhook→coordinator→CRM identity→sales→compliance→outbox→router→fake adapter→audit) with ZERO edits to business core; fails if core ever imports a provider module.

## D17. Migration Safety
Rehearse on COPY of live DB (row counts + integrity + spot queries) BEFORE prod. Backup taken before deploy. Service restart applies migrations automatically via open_database. Rollback = restore backup (renames are reversible by inverse RENAME; forward-only policy documented).

## D18. Explicitly NOT done (scope discipline)
No Postgres/Redis/K8s/agent-framework/multi-tenancy/RBAC; no real 2nd customer channel beyond FakeAdapter proof (Telegram customer adapter = recommended next step); website phone→contact_whatsapp behavior preserved (business assumption, revisited with 2nd channel); sync adoption still text-type scoped (documented).
