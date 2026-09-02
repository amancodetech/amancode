"""Process-Aware Environment and Filesystem Isolation Utilities."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Generator


@contextlib.contextmanager
def isolated_env(**overrides) -> Generator[dict[str, str], None, None]:
    """Temporarily override environment variables and guarantee clean restoration."""
    orig_env = dict(os.environ)
    try:
        os.environ.update(overrides)
        yield os.environ
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


@contextlib.contextmanager
def isolated_temp_dir(prefix: str = "amancore_test_") -> Generator[Path, None, None]:
    """Provide a dedicated process- and worker-isolated temporary directory."""
    worker_id = os.environ.get("TEST_WORKER_ID") or os.environ.get("PYTEST_XDIST_WORKER") or f"pid_{os.getpid()}"
    safe_prefix = f"{prefix}{worker_id}_"
    with tempfile.TemporaryDirectory(prefix=safe_prefix) as temp_dir:
        worker_root = Path(temp_dir) / worker_id
        worker_root.mkdir(parents=True, exist_ok=True)
        yield worker_root
