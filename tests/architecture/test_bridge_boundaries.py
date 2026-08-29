"""Architecture boundary test (owner spec §39) — AmanCore core must NEVER
import or embed platform implementations (Baileys, facebook-chat-api,
instagram-private-api, Playwright/Puppeteer). Those live ONLY in the
bridge/browser-agent layers (bridge/, outside the core package)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[2] / "amancore"

# banned platform implementations + automation drivers inside amancore/
BANNED_PATTERNS = (
    re.compile(r"\b(baileys|puppeteer|playwright)\b", re.IGNORECASE),
    re.compile(r"facebook[-_ ]?chat[-_ ]?api", re.IGNORECASE),
    re.compile(r"instagram[-_ ]?private[-_ ]?api", re.IGNORECASE),
    re.compile(r"\binstagrapi\b", re.IGNORECASE),
)

# The architectural boundary is about EXECUTABLE references: import/from
# statements (and JS-style require()). Prose in docstrings/comments may
# legitimately name the libraries.
_IMPORT_LINE = re.compile(r"^\s*(?:import|from)\s+[A-Za-z_]")
_REQUIRE_LINE = re.compile(r"\brequire\s*\(")


def _iter_core_code_lines():
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        rel = path.relative_to(CORE_ROOT)
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if not (_IMPORT_LINE.match(line) or _REQUIRE_LINE.search(line)):
                    continue
                yield rel, lineno, stripped


class BridgeBoundaryTests(unittest.TestCase):
    def test_core_never_imports_platform_implementations(self):
        violations = []
        for rel, lineno, line in _iter_core_code_lines():
            for pattern in BANNED_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            violations, [],
            "AmanCore core references a platform implementation — "
            "it must live in bridge/ (owner spec §39):\n" + "\n".join(violations))

    def test_core_imports_only_approved_external_http_libs(self):
        """External dependencies inside the core are the DECLARED set
        (requests + yaml). Everything stdlib is fine; guard against a
        platform SDK sneaking into the dependency set."""
        import sys

        approved_external = {"requests", "yaml"}
        import_names = re.compile(
            r"^(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)")
        violations = []
        for rel, lineno, line in _iter_core_code_lines():
            m = import_names.match(line)
            if not m:
                continue
            root_mod = m.group(1).split(".")[0]
            if root_mod in approved_external or root_mod == "amancore" \
                    or root_mod.startswith("_") \
                    or root_mod in sys.stdlib_module_names:
                continue
            violations.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(
            violations, [],
            "Unexpected non-stdlib import in amancore core — extend the "
            "approved list deliberately, never implicitly:\n"
            + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
