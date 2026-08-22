# Configuration

- `configs/app.yaml` — env, database path, log level, shadow rate.
- `configs/models.yaml` — task routing, providers, per-token pricing.
- `configs/pricing.yaml` — shadow rate, markup, minimum multipliers, market multipliers.
- `configs/lead_scoring.yaml` — weights + thresholds.
- `configs/retention.yaml` — retention policies.
- `.env` — local secrets (never committed).

All values are configurable; nothing business-critical is hardcoded.
