"""Professional pricing architecture tests.

Covers the single-source pricing identity (registry), add-on compatibility,
scope-change fingerprinting and the immutable snapshot lifecycle.
"""

import tempfile
import unittest
from pathlib import Path

from amancore.pricing import registry
from amancore.pricing.engine import PricingEngine
from tests.common import TempDirTestCase, make_db, make_brain


class RegistryIdentityTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        self.brain = self.store.current()[1]

    def test_service_to_offer_to_policy_key(self):
        # business_website_system -> offer website_system -> policy key website_standard
        self.assertEqual(
            registry.offer_for_service(self.brain, "business_website_system"),
            "website_system")
        self.assertEqual(
            registry.policy_key(self.brain, "business_website_system"),
            "website_standard")
        self.assertEqual(
            registry.policy_key(self.brain, "business_system_mini_erp"),
            "business_system")

    def test_base_hours_from_profile(self):
        self.assertEqual(
            registry.base_hours(self.brain, "business_website_system"), 20.0)
        self.assertEqual(
            registry.base_hours(self.brain, "business_system_mini_erp"), 120.0)

    def test_category_to_service(self):
        self.assertEqual(
            registry.service_for_category(self.brain, "website"),
            "business_website_system")
        self.assertEqual(
            registry.service_for_category(self.brain, "ecommerce"),
            "ecommerce_store")

    def test_complexity_level_deterministic(self):
        low = registry.complexity_level({"pages": 3})
        high = registry.complexity_level(
            {"pages": 20, "payments": True, "member_areas": True,
             "custom_dashboards": True, "integrations": True})
        self.assertEqual(low, "low")
        self.assertEqual(high, "high")


class AddOnCompatibilityTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        self.brain = self.store.current()[1]

    def test_valid_addons(self):
        res = registry.compatible_add_ons(
            self.brain, "business_website_system",
            ["whatsapp_integration", "multilingual"])
        self.assertIn("whatsapp_integration", res["valid"])
        self.assertEqual(res["invalid"], [])

    def test_incompatible_addon_rejected(self):
        # whatsapp_ordering is incompatible with mobile_app
        res = registry.compatible_add_ons(self.brain, "mobile_app",
                                          ["whatsapp_ordering"])
        self.assertIn("whatsapp_ordering", res["invalid"])
        self.assertIn("not compatible", res["reasons"]["whatsapp_ordering"])

    def test_requires_rule_enforced(self):
        # whatsapp_ordering requires whatsapp_integration
        res = registry.compatible_add_ons(
            self.brain, "ecommerce_store", ["whatsapp_ordering"])
        self.assertIn("whatsapp_ordering", res["invalid"])
        self.assertIn("requires", res["reasons"]["whatsapp_ordering"])
        # supplying the dependency makes it valid
        res2 = registry.compatible_add_ons(
            self.brain, "ecommerce_store",
            ["whatsapp_ordering", "whatsapp_integration"])
        self.assertIn("whatsapp_ordering", res2["valid"])

    def test_unknown_addon_rejected(self):
        res = registry.compatible_add_ons(self.brain, "website", ["nope"])
        self.assertIn("nope", res["invalid"])

    def test_addon_adds_deterministic_hours_and_price(self):
        eng = PricingEngine(self.store)
        base = eng.price({"service": "business_website_system",
                          "estimated_hours": 20, "market": "gcc",
                          "risk_level": "medium"})
        with_addons = eng.price({"service": "business_website_system",
                                 "estimated_hours": 20, "market": "gcc",
                                 "risk_level": "medium",
                                 "add_ons": ["whatsapp_integration", "multilingual"]})
        # 20 + 8 + 6 = 34 hours
        self.assertEqual(with_addons["estimated_hours"], 34)
        self.assertGreater(with_addons["target_price"], base["target_price"])


class ScopeFingerprintTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)

    def test_stable_for_same_inputs(self):
        facts = {"pages": 7, "languages": 2, "payments": True}
        a = registry.scope_fingerprint("website", facts)
        b = registry.scope_fingerprint("website", {"payments": True,
                                                   "languages": 2,
                                                   "pages": 7})
        self.assertEqual(a, b)

    def test_changes_when_scope_changes(self):
        a = registry.scope_fingerprint("website", {"pages": 7})
        b = registry.scope_fingerprint("website", {"pages": 15})
        self.assertNotEqual(a, b)

    def test_small_flag_and_addons_are_significant(self):
        base = registry.scope_fingerprint("website", {"pages": 3})
        small = registry.scope_fingerprint("website", {"pages": 3}, small=True)
        with_addon = registry.scope_fingerprint(
            "website", {"pages": 3}, add_ons=["multilingual"])
        self.assertNotEqual(base, small)
        self.assertNotEqual(base, with_addon)


class SnapshotLifecycleTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.store = make_brain(self.tmp)
        self.db = make_db(self.tmp / "life.db")
        from amancore.crm.service import CRMService
        from amancore.pricing.snapshot import PricingSnapshotStore
        self.crm = CRMService(self.db)
        self.snaps = PricingSnapshotStore(self.db)
        self.engine = PricingEngine(self.store)

    def _result(self):
        return self.engine.price({"service": "business_website_system",
                                  "estimated_hours": 20, "market": "gcc",
                                  "risk_level": "medium"})

    def _opp(self) -> str:
        lead_id = self.crm.create_lead(name="Test", market="gcc",
                                       language="ar")
        opp_id = self.crm.create_opportunity(
            lead_id, "business_website_system", offer_id="website_system",
            stage="offer_recommended", scope_summary="test scope")
        return opp_id

    def test_supersede_keeps_old_immutable_and_hides_it(self):
        opp_id = self._opp()
        snap_id = self.snaps.create(
            opp_id, self._result(),
            approved_price=4200, approved_by="owner", business_brain_version=1,
            scope_fingerprint="fp-v1")
        # active lookup returns it
        self.assertIsNotNone(self.snaps.get_for_opportunity(opp_id))
        # supersede it
        self.snaps.supersede(snap_id, superseded_by="scope_change")
        old = self.snaps.get(snap_id)
        self.assertEqual(old["status"], "superseded")
        # it no longer shows as the active approved snapshot
        self.assertIsNone(self.snaps.get_for_opportunity(opp_id))
        # the immutable record still exists and is unchanged in price
        self.assertEqual(old["approved_price"], 4200)


if __name__ == "__main__":
    unittest.main()
