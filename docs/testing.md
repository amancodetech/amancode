# Testing

```bash
python -m amancore.cli test
# or
python -m unittest discover -s tests -t .
```

Suites:

- `tests/unit` — business brain, crm, events, risk/policy, approvals/audit, router.
- `tests/integration` — full foundation chain.
- `tests/security` — gitignore/env/audit-immutability/idempotency.
- `tests/architecture` — import/boundary rules (sqlite3 + brain-writer isolation).
