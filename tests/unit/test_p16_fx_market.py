"""P1/P0 — Market + FX doctrine verification tests.

Owner-approved doctrine:
  - USD is the FIXED pricing base.
  - Arab market (gcc) is priced in USD, always.
  - Indonesian market (the DEFAULT) is priced in IDR, converted from the USD
    base at the Brain-pinned daily rate.
  - Every priced correspondence freezes (rate, date); later Brain rate
    updates never rewrite an issued price (T3 replays stored figures).
"""

from __future__ import annotations

import unittest

from amancore.conversation.quality_guard import QualityGuard
from amancore.conversation.pricing_flow import QuoteFlow
from amancore.crm.service import CRMService
from amancore.pricing import fx as _fx
from amancore.pricing.snapshot import PricingSnapshotStore
from tests.common import TempDirTestCase, make_brain, make_db


class FxMarketTests(TempDirTestCase, unittest.TestCase):
    def test_resolve_market_matrix(self):
        self.assertEqual(_fx.resolve_market("ar", {}), ("gcc", "USD"))
        self.assertEqual(_fx.resolve_market("AR", {}), ("gcc", "USD"))
        self.assertEqual(_fx.resolve_market("id", {}), ("indonesia", "IDR"))
        self.assertEqual(_fx.resolve_market("en", {}), ("indonesia", "IDR"))
        # Default market is Indonesian, NOT Arab.
        self.assertEqual(_fx.resolve_market(None, {}), ("indonesia", "IDR"))
        self.assertEqual(_fx.resolve_market("", {}), ("indonesia", "IDR"))

    def test_conversion_math_and_formatting(self):
        rate, date = _fx.get_usd_idr_rate({})
        self.assertEqual(rate, _fx.FALLBACK_USD_IDR)
        self.assertTrue(date)
        self.assertEqual(_fx.usd_to_idr(1500, 17650), 26500000)
        self.assertEqual(_fx.format_idr(26500000), "Rp26.500.000")
        self.assertIn("USD", _fx.format_usd(1500))


class EstimateCurrencyTests(TempDirTestCase, unittest.TestCase):
    def _flow(self):
        brain = make_brain(self.tmp)
        db = make_db(self.tmp / "fx.db")
        crm = CRMService(db)
        flow = QuoteFlow(db, crm, brain, PricingSnapshotStore(db),
                         dispatcher=None, owner_alert=lambda *a, **k: None)
        lead_id = crm.create_lead(source_channel="whatsapp",
                                  contact_whatsapp="628110000001")
        return flow, crm.get_lead(lead_id), brain

    def test_arabic_estimate_is_usd(self):
        flow, _lead, _brain = self._flow()
        est = flow.estimate({"language": "ar"}, "website")
        self.assertIsNotNone(est)
        self.assertEqual(est["currency"], "USD")
        self.assertEqual(est["market"], "gcc")
        self.assertIsNone(est["fx_rate"])

    def test_indonesian_estimate_is_idr_with_frozen_fx(self):
        flow, _lead, brain = self._flow()
        est = flow.estimate({"language": "id"}, "website")
        self.assertIsNotNone(est)
        self.assertEqual(est["currency"], "IDR")
        self.assertEqual(est["market"], "indonesia")
        _rate, _date = _fx.get_usd_idr_rate(brain.current()[1])
        self.assertEqual(est["fx_rate"], _rate)
        self.assertEqual(est["fx_date"], _date)
        # USD base preserved for audit; IDR = base x rate.
        self.assertEqual(est["low"],
                        _fx.usd_to_idr(est["usd_base_low"], _rate))
        self.assertEqual(est["high"],
                        _fx.usd_to_idr(est["usd_base_high"], _rate))

    def test_default_market_is_indonesia_idr(self):
        flow, _lead, _brain = self._flow()
        est = flow.estimate({}, "website")
        self.assertEqual(est["market"], "indonesia")
        self.assertEqual(est["currency"], "IDR")

    def test_fx_freeze_in_approval_and_snapshot(self):
        """A later Brain rate change must NOT rewrite an issued price."""
        flow, lead, _brain = self._flow()
        est = flow.estimate({"language": "id"}, "website")
        aid = flow.request_owner_approval(lead, est,
                                          scope_fingerprint="fp-test")
        import json as _json
        payload = _json.loads(flow.approvals.get(aid)["payload"])
        self.assertEqual(payload["fx_rate"], est["fx_rate"])
        self.assertEqual(payload["fx_date"], est["fx_date"])
        self.assertEqual(payload["usd_base_high"], est["usd_base_high"])
        snap_id = flow.finalize(aid, approved_by="owner_console")
        snap = flow.snapshots.get(snap_id)
        self.assertEqual(snap["currency"], "IDR")
        self.assertEqual(float(snap["approved_price"]), est["high"])


class GuardCurrencyAliasTests(unittest.TestCase):
    def test_arabic_dollar_word_satisfies_usd(self):
        g = QualityGuard()
        plan = {"mode": "COMMERCIAL", "language": "ar",
                "commercial": {"tier": "T1", "currency": "USD"},
                "quality": {"allowed_numbers": ["1500", "4200"]}}
        res = g.check("تبدأ عادةً من 1500 وقد تصل إلى 4200 دولار أمريكي؟",
                      plan=plan)
        self.assertNotIn("wrong_currency:دولار",
                         ",".join(res["violations"]))

    def test_rupiah_aliases_satisfy_idr(self):
        g = QualityGuard()
        plan = {"mode": "COMMERCIAL", "language": "id",
                "commercial": {"tier": "T1", "currency": "IDR"},
                "quality": {"allowed_numbers": ["26500000", "74100000"]}}
        res = g.check("mulai dari Rp26.500.000 hingga Rp74.100.000 IDR?",
                      plan=plan)
        self.assertTrue(res["allowed"], res["violations"])

    def test_currency_mismatch_still_blocked(self):
        g = QualityGuard()
        plan = {"mode": "COMMERCIAL", "language": "ar",
                "commercial": {"tier": "T1", "currency": "USD"},
                "quality": {"allowed_numbers": ["1500"]}}
        res = g.check("السعر 1500 روبية؟", plan=plan)
        self.assertIn("wrong_currency:روبية", res["violations"])


if __name__ == "__main__":
    unittest.main()
