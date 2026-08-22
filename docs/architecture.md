# Architecture (Foundation)

Layered, event-driven, single-process (local) runtime.

```
Channels (future) → Channel Adapters (future) → Canonical Events
   → Orchestrator (future) → Agents (future) → Skills/Functions
   → Business Brain / CRM / Memory  → Model Router → Providers
```

Built in Phase 3A:

| Component | Role |
|---|---|
| `storage/` | SQLite access + schema (only module importing sqlite3) |
| `business_brain/` | versioned config + deterministic Writer |
| `crm/` | controlled data service (Leads/Customers/Opportunities/Projects/CarePlans/Conversations) |
| `services/events` | canonical event + dispatcher + idempotency |
| `services/risk` | deterministic risk classification (LOW→CRITICAL) |
| `services/policy` | deterministic allow/approval/escalate/deny |
| `services/approvals` | auditable approval workflow |
| `services/audit` | append-only audit trail |
| `routing/` | config-driven model router + providers + usage tracking |

Deferred (later phases): Agents, channels, scheduler, analytics, support,
website, WhatsApp, etc.
