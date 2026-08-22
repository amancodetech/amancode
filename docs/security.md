# Security

- Secrets live only in `.env` (git-ignored) and are read by name, never in code.
- `.env.example` is the committed template (no values).
- Only `amancore/storage/db.py` imports `sqlite3` (architecture-tested).
- Only `BrainWriter` may create Business Brain versions (architecture-tested).
- Audit is append-only (no update/delete methods).
- Idempotency prevents duplicate external actions.
- Least privilege + tool allowlists will be applied to Agents in later phases.
