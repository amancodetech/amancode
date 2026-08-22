import copy
import unittest

from amancore.business_brain.validator import validate_brain
from amancore.business_brain.writer import BrainWriter
from amancore.errors import PermissionDenied, ValidationError
from tests.common import TempDirTestCase, make_brain


class BusinessBrainTest(TempDirTestCase, unittest.TestCase):
    def test_load_current_v1(self):
        store = make_brain(self.tmp)
        version, data = store.current()
        self.assertEqual(version, 1)
        self.assertEqual(data["company"]["name"], "AmanCore")

    def test_seed_is_valid(self):
        store = make_brain(self.tmp)
        _, data = store.current()
        self.assertEqual(validate_brain(data), [])

    def test_validate_missing_section(self):
        store = make_brain(self.tmp)
        _, data = store.current()
        del data["pricing_policy"]
        self.assertTrue(any("pricing_policy" in e for e in validate_brain(data)))

    def test_validate_unsupported_market(self):
        store = make_brain(self.tmp)
        _, data = store.current()
        data["pricing_policy"]["market_multiplier"]["france"] = 1.0
        self.assertTrue(any("france" in e for e in validate_brain(data)))

    def test_validate_duplicate_offer_id(self):
        store = make_brain(self.tmp)
        _, data = store.current()
        data["offers"].append(dict(data["offers"][0]))
        self.assertTrue(any("duplicate" in e for e in validate_brain(data)))

    def test_writer_approve_creates_version(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        _, data = store.current()
        data["company"]["name"] = "AmanCore v2"
        pid = writer.propose(data, requested_by="owner", reason="rename")
        new_version = writer.approve(pid, approved_by="owner")
        self.assertEqual(new_version, 2)
        self.assertEqual(store.current()[1]["company"]["name"], "AmanCore v2")
        self.assertEqual(store.get(1)["company"]["name"], "AmanCore")

    def test_writer_reject(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        _, data = store.current()
        data["company"]["name"] = "X"
        pid = writer.propose(data, "owner", "r")
        writer.reject(pid, "owner", "no")
        self.assertEqual(store.current()[0], 1)

    def test_writer_propose_invalid_raises(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        with self.assertRaises(ValidationError):
            writer.propose({"company": {}}, "owner", "bad")

    def test_approve_non_pending_raises(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        _, data = store.current()
        pid = writer.propose(data, "owner", "r")
        writer.approve(pid, "owner")
        with self.assertRaises(PermissionDenied):
            writer.approve(pid, "owner")

    def test_rollback(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        _, data = store.current()
        original = copy.deepcopy(data)
        data["company"]["name"] = "Changed"
        pid = writer.propose(data, "owner", "change")
        writer.approve(pid, "owner")
        v3 = writer.rollback(1, "owner", "owner", "undo")
        self.assertEqual(v3, 3)
        self.assertEqual(store.current()[1]["company"]["name"], original["company"]["name"])

    def test_diff(self):
        store = make_brain(self.tmp)
        writer = BrainWriter(store, proposals_dir=self.tmp / "proposals")
        _, data = store.current()
        data["company"]["name"] = "Diffed"
        pid = writer.propose(data, "owner", "diff")
        writer.approve(pid, "owner")
        changes = store.diff(1, 2)
        self.assertTrue(any("company.name" in c for c in changes))


if __name__ == "__main__":
    unittest.main()
