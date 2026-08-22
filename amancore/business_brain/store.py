"""Business Brain read-only versioned store (immutable versions on disk)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..errors import BusinessBrainError, NotFoundError
from ..ids import utcnow

_VERSION_DIR = "versions"
_INDEX_FILE = "_index.json"


def _deep_diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Return list of changed paths between two structures."""
    changes: list[str] = []
    if type(a) is not type(b):
        changes.append(f"{path or '/'}: type changed {type(a).__name__} -> {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                changes.append(f"{p}: added")
            elif k not in b:
                changes.append(f"{p}: removed")
            else:
                changes.extend(_deep_diff(a[k], b[k], p))
    elif isinstance(a, list):
        if a != b:
            changes.append(f"{path or '/'}: list changed")
    elif a != b:
        changes.append(f"{path or '/'}: {a!r} -> {b!r}")
    return changes


class BrainStore:
    """Reads current + historical Business Brain versions."""

    def __init__(self, brain_dir: Path):
        self.brain_dir = Path(brain_dir)
        self.seed_file = self.brain_dir / "data" / "v1.yaml"
        self.versions_dir = self.brain_dir / _VERSION_DIR
        self.index_path = self.versions_dir / _INDEX_FILE
        if not self.seed_file.exists():
            raise BusinessBrainError(f"missing seed business brain: {self.seed_file}")

    # -- internal ---------------------------------------------------------
    def _load_seed(self) -> dict:
        return yaml.safe_load(self.seed_file.read_text(encoding="utf-8")) or {}

    def _load_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _version_file(self, number: int) -> Path:
        return self.versions_dir / f"v{number:04d}.yaml"

    # -- public -----------------------------------------------------------
    def current(self) -> tuple[int, dict]:
        """Return (version_number, content) of the latest version."""
        index = self._load_index()
        if not index:
            return 1, self._load_seed()
        latest = max(index, key=lambda e: e["version"])
        return latest["version"], self._read_version(latest["version"])

    def _read_version(self, number: int) -> dict:
        if number == 1:
            return self._load_seed()
        f = self._version_file(number)
        if not f.exists():
            raise NotFoundError(f"business brain version {number} not found")
        return yaml.safe_load(f.read_text(encoding="utf-8")) or {}

    def get(self, number: int) -> dict:
        return self._read_version(number)

    def versions(self) -> list[dict]:
        """Metadata list including the immutable seed v1."""
        seed_meta = {
            "version": 1,
            "created_at": None,
            "created_by": "owner",
            "reason": "initial business brain from strategy v1.2",
            "previous_version": None,
            "approval_status": "approved",
            "proposal_id": None,
        }
        return [seed_meta] + self._load_index()

    def next_version_number(self) -> int:
        index = self._load_index()
        if not index:
            return 2
        return max(e["version"] for e in index) + 1

    def diff(self, a: int, b: int) -> list[str]:
        return _deep_diff(self._read_version(a), self._read_version(b))

    # write support (called only by BrainWriter) --------------------------
    def _append_version(
        self,
        number: int,
        content: dict,
        meta: dict,
    ) -> None:
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self._version_file(number).write_text(
            yaml.safe_dump(content, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        index = self._load_index()
        index.append(
            {
                "version": number,
                "created_at": utcnow(),
                "created_by": meta["created_by"],
                "reason": meta["reason"],
                "previous_version": meta["previous_version"],
                "approval_status": meta["approval_status"],
                "proposal_id": meta.get("proposal_id"),
            }
        )
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
