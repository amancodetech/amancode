# Test fixtures

The primary business-brain fixture is the immutable seed:

    amancore/business_brain/data/v1.yaml

Tests copy it into an isolated temp directory (see `tests/common.py`) so
versioning/rollback tests never mutate the real seed.

Add JSON/YAML fixtures here as future phases introduce richer payloads
(events, proposals, conversations).
