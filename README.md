# AmanCode — Foundation (Phase 3A)

AI Marketing & Sales Operating System for AmanCode. This phase delivers the
**Foundation only**: security baseline, configuration, SQLite, Business Brain
(+ versioned writer), CRM data service, canonical events, policy/risk engines,
approval service, audit, and a config-driven model router.

## Quick start

```bash
# from aman-core/
python -m amancore.cli config check
python -m amancore.cli health
python -m amancore.cli test
```

## Layout

```
aman-core/
├── amancore/            # runtime package
│   ├── storage/         # SQLite + schema
│   ├── business_brain/  # versioned config + writer
│   ├── crm/             # controlled data service
│   ├── services/        # events/risk/policy/approvals/audit/owner_alert
│   └── routing/         # model router + providers
├── configs/             # app/models/pricing/lead_scoring/retention
├── tests/               # unit/integration/security/architecture
├── docs/                # documentation + runbook
├── scripts/             # backup/validate
├── .env.example         # env template (committed)
└── .env                 # local secrets (git-ignored)
```

## Principles

- Business Brain = versioned business configuration (not CRM state).
- Agents read Business Brain only; writes go through the BrainWriter.
- CRM is the only gateway to tables (agents never touch SQLite directly).
- Official-API-first for channels (none built yet).
- No secrets in code, prompts, config, or Git.
