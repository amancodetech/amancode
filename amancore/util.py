"""Small shared utilities for LLM-based skills."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Return the aman-core project root (parent of the amancore package)."""
    return Path(__file__).resolve().parent.parent


def extract_json(text: str) -> Any:
    """Extract the first JSON object/array from a model response."""
    if not text:
        return None
    # strip code fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # fallback: find first { ... } or [ ... ] block
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == opener:
                depth += 1
            elif cleaned[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def run_json(router, task_class: str, prompt: str, default: Any = None) -> Any:
    """Route a prompt and parse JSON, returning `default` on any failure."""
    if router is None:
        return default
    try:
        result = router.route(task_class, [{"role": "user", "content": prompt}])
        return extract_json(result.text)
    except Exception:
        return default


def run_text(router, task_class: str, prompt: str, default: str = "") -> str:
    """Route a prompt and return raw text, returning `default` on failure."""
    if router is None:
        return default
    try:
        result = router.route(task_class, [{"role": "user", "content": prompt}])
        return result.text.strip()
    except Exception:
        return default
