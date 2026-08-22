# Runbook

## Run health check
```bash
python -m amancore.cli health
```

## Run tests
```bash
python -m amancore.cli test
```

## Inspect config
```bash
python -m amancore.cli config check
```

## Business Brain
```bash
python -m amancore.cli brain validate
python -m amancore.cli brain versions
```

## Audit trail
```bash
python -m amancore.cli audit recent -n 20
```

## Where things live
- Database: `storage/aman_core.db` (git-ignored)
- Logs: stdout (structured via `amancore.log`)
- Business Brain: `amancore/business_brain/data/v1.yaml` + `versions/`

## Backup
```bash
python scripts/backup_db.py
python scripts/validate_backup.py
```

## Restore a Business Brain version
Use `BrainWriter.rollback(target_version, ...)` (programmatic) or restore
`versions/vNNNN.yaml` via the writer. Versions are immutable files.

## Model router sanity
`python -m amancore.cli health` reports the configured strategy routing order.
