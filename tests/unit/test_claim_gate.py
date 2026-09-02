import unittest

from amancore.services.claim_gate import (
    CLEAN,
    FORBIDDEN,
    NEEDS_VERIFICATION,
    ClaimGate,
)
from tests.common import TempDirTestCase, make_brain


class ClaimGateTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.gate = ClaimGate(make_brain(self.tmp))

    def test_clean(self):
        d = self.gate.check("AmanCode builds multilingual business websites")
        self.assertEqual(d.status, CLEAN)

    def test_forbidden(self):
        d = self.gate.check("We guarantee revenue growth")
        self.assertEqual(d.status, FORBIDDEN)

    def test_needs_verification_on_risky_keyword(self):
        d = self.gate.check("Our clients love us")
        self.assertEqual(d.status, NEEDS_VERIFICATION)


if __name__ == "__main__":
    unittest.main()
