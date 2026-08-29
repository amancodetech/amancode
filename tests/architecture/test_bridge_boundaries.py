"""Architecture boundary test (owner spec §39) — AmanCore core must NEVER
import platform implementations (Baileys, facebook-chat-api,
instagram-private-api, Playwright/Puppeteer). Those live ONLY in the
bridge/browser-agent layers (bridge/, outside the core package).

Parsing uses ast — real imports only, no prose false-positives."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[2] / "amancore"

# banned platform implementations inside the core (case-insensitive module names)
BANNED_MODULE_FRAGMENTS = (
    "baileys", "puppeteer", "playwright", "instagrapi",
    "facebook-chat-api", "facebook_chat_api", "instagram-private-api",
    "instagram_private_api",
)

# declared external dependencies inside the core (everything stdlib is fine)
APPROVED_EXTERNAL = {"requests", "yaml", "google"}


def _iter_core_imports():
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        rel = path.relative_to(CORE_ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a core file that doesn't parse is a failure too
            yield rel, 0, "", f"syntax error: {exc}"
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield rel, node.lineno, alias.name, None
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                # level > 0 → relative import ('from .ids import x') — the
                # module name is intra-core even though ast reports it bare
                yield rel, node.lineno, ("." * (node.level or 0)) + module, None


class BridgeBoundaryTests(unittest.TestCase):
    def test_core_never_imports_platform_implementations(self):
        violations = []
        for rel, lineno, module, error in _iter_core_imports():
            if error:
                violations.append(f"{rel}:{lineno}: {error}")
                continue
            low = module.lower()
            for frag in BANNED_MODULE_FRAGMENTS:
                if frag in low:
                    violations.append(f"{rel}:{lineno}: import {module}")
        self.assertEqual(
            violations, [],
            "AmanCore core imports a platform implementation — it must live "
            "in bridge/ (owner spec §39):\n" + "\n".join(violations))

    def test_core_imports_only_declared_external_dependencies(self):
        violations = []
        for rel, lineno, module, error in _iter_core_imports():
            if error:
                continue  # covered by the syntax check above
            root_mod = (module.split(".")[0] or "").strip()
            if not root_mod or root_mod == "amancore":
                continue  # relative + intra-core imports
            if root_mod in sys.stdlib_module_names:
                continue
            if root_mod not in APPROVED_EXTERNAL:
                violations.append(f"{rel}:{lineno}: import {module}")
        self.assertEqual(
            violations, [],
            "Unexpected non-stdlib import in amancore core — extend the "
            "approved list deliberately, never implicitly:\n"
            + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
