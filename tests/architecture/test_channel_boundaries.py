"""Channel-boundary enforcement (always-on architecture tests).

Rules enforced:
1. Domain packages must NOT import provider channel implementations.
2. Domain packages must NOT contain WhatsApp vocabulary literals
   (wa_id / wamid / contact_whatsapp / 'whatsapp' string).
3. EVENT_TYPES carries no provider-prefixed message types.

Whitelists are EXPLICIT and justified — every addition needs a reason.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "amancore"

# Domain packages where channel/provider coupling is FORBIDDEN.
DOMAIN_DIRS = [
    "crm", "sales", "support", "pricing", "analytics", "insights",
    "services", "compliance", "agents", "business_brain", "routing",
    "skills", "functions",
]

# Provider modules that only adapter/composition layers may import.
PROVIDER_MODULES = ("channels.whatsapp", "channels.wa_errors")

# Justified operational exceptions (provider-aware infrastructure):
# - ops/smoke.py: end-to-end WHATSAPP pipeline smoke (operational telemetry)
IMPORT_WHITELIST = {"ops/smoke.py"}

# Justified literal exceptions — each needs a stated reason:
# - crm/service.py: LEGACY BRIDGE find_lead_by_whatsapp() backfills identity
#   rows from contact_whatsapp (migration compatibility, design D4).
# - compliance/guard.py: SendValve keeps channel="whatsapp" DEFAULT so the
#   historical single-channel behavior is unchanged (design D10); callers
#   pass explicit channels.
LITERAL_WHITELIST = {
    "crm/service.py": "legacy identity bridge (design D4)",
    "compliance/guard.py": "legacy valve channel default (design D10)",
    "analytics/briefing.py": "multi-channel aggregate executive briefing metrics",
}

LITERAL_PATTERN = re.compile(
    r"\bwa_id\b|\bwamid\b|\bcontact_whatsapp\b|['\"]whatsapp['\"]"
)


def _py_files(rel_dir: str):
    return sorted((CORE / rel_dir).rglob("*.py"))


class TestProviderImportBoundaries(unittest.TestCase):
    def test_domain_packages_do_not_import_providers(self):
        violations = []
        for d in DOMAIN_DIRS:
            for f in _py_files(d):
                rel = f.relative_to(CORE).as_posix()
                if rel in IMPORT_WHITELIST:
                    continue
                src = f.read_text(encoding="utf-8")
                for m in re.finditer(
                        r"from\s+\.{0,2}[\w.]*\b("
                        r"|".join(PROVIDER_MODULES) + r")\b|"
                        r"import\s+[\w.]*\b("
                        + "|".join(PROVIDER_MODULES) + r")\b", src):
                    violations.append(f"{rel}: {src[:m.start()].count(chr(10)) + 1}")
        self.assertEqual(violations, [],
                         "domain packages import provider channel code:\n"
                         + "\n".join(violations))

    def test_outbox_worker_has_no_provider_imports(self):
        src = (CORE / "channels" / "outbox.py").read_text(encoding="utf-8")
        # wa_errors categories are shared retry taxonomy, but the WORKER body
        # must not reference provider error TYPES directly anymore.
        self.assertNotIn("WhatsAppSendError", src.split("FAST_DEAD_CATEGORIES")[0])


class TestVocabularyLeakage(unittest.TestCase):
    def test_domain_packages_have_no_wa_literals(self):
        violations = []
        for d in DOMAIN_DIRS:
            for f in _py_files(d):
                rel = f.relative_to(CORE).as_posix()
                if rel in LITERAL_WHITELIST:
                    continue
                for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith('"""'):
                        continue
                    if LITERAL_PATTERN.search(line):
                        violations.append(f"{rel}:{i}: {stripped[:90]}")
        self.assertEqual(violations, [],
                         "WhatsApp vocabulary leaked into domain code:\n"
                         + "\n".join(violations))

    def test_event_types_are_channel_neutral(self):
        from amancore.services.events import EVENT_TYPES

        prefixed = [t for t in EVENT_TYPES if t.startswith(("whatsapp.",
                                                            "telegram.",
                                                            "instagram.",
                                                            "tiktok.",
                                                            "messenger.",
                                                            "youtube."))]
        self.assertEqual(prefixed, [], f"provider-prefixed event types: {prefixed}")
