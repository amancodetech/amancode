"""Phase 3G evals — 12 scenarios (spec section 53), dedicated test DB only."""

import json
import unittest
from pathlib import Path

from amancore.analytics.service import AnalyticsService
from amancore.insights.decisions import DecisionSupportService
from amancore.insights.engine import InsightsEngine
from amancore.insights.memory import InsightMemory
from amancore.insights.model import new_insight, new_recommendation
from amancore.services.approvals import ApprovalService
from tests.common import TempDirTestCase, make_brain, make_db
from tests.insights_seed import (
    seed_lead,
    seed_opportunity,
    seed_project,
    seed_support_case,
    seed_usage,
    seed_won_deal,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class InsightsEvals(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        import yaml

        self.cfg = yaml.safe_load(
            (Path(__file__).resolve().parent.parent.parent / "configs" / "insights.yaml")
            .read_text(encoding="utf-8")
        )
        self._reset_services()

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def _reset_services(self):
        self._db_seq = getattr(self, "_db_seq", 0) + 1
        self.db = make_db(self.tmp / f"t_{self._db_seq}.db")
        self.analytics = AnalyticsService(self.db)
        self.mem = InsightMemory(self.db)
        self.engine = InsightsEngine(self.db, analytics=self.analytics, config=self.cfg)
        self.dss = DecisionSupportService(
            self.db, memory=self.mem, approval_service=ApprovalService(self.db),
        )

    def _seed(self, scenario_id: str) -> None:
        if scenario_id == "lead_source_improvement":
            for _ in range(6):
                seed_lead(self.db, source="whatsapp", stage="qualified", score=50, days_ago=3)
            for _ in range(2):
                seed_lead(self.db, source="direct", stage="nurture", score=10, days_ago=3)
        elif scenario_id == "margin_issue":
            for _ in range(5):
                seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)
        elif scenario_id == "pricing_objections":
            for _ in range(4):
                seed_lead(self.db, days_ago=1)
            rows = self.db.execute("SELECT lead_id FROM leads").fetchall()
            for i, r in enumerate(rows):
                self.db.execute(
                    "INSERT INTO conversations (conversation_id, lead_id, channel, objections, created_at, updated_at) "
                    "VALUES (?, ?, 'whatsapp', '[\"too_expensive\"]', datetime('now'), datetime('now'))",
                    (f"conv-{i}", r["lead_id"]),
                )
            self.db.commit()
        elif scenario_id == "content_success":
            from tests.insights_seed import seed_content

            seed_content(self.db, content_id="c-best")
            seed_content(self.db, content_id="c-other")
            for _ in range(5):
                seed_lead(self.db, source="content", days_ago=1)
            rows = self.db.execute("SELECT lead_id FROM leads").fetchall()
            for i, r in enumerate(rows):
                self.db.execute(
                    "UPDATE leads SET source_content_id = ? WHERE lead_id = ?",
                    ("c-best" if i < 4 else "c-other", r["lead_id"]),
                )
            self.db.commit()
        elif scenario_id in ("support_recurrence", "saas_candidate"):
            for _ in range(4):
                seed_support_case(self.db, category="technical_support")
        elif scenario_id == "ai_cost_spike":
            for _ in range(6):
                seed_usage(self.db, model="glm-dummy-pro", cost=0.5)
            seed_usage(self.db, model="glm-dummy-flash", cost=0.1)
        elif scenario_id == "capacity_bottleneck":
            for _ in range(6):
                seed_project(self.db, hours=90.0)
        elif scenario_id == "insufficient_data":
            seed_lead(self.db, days_ago=1)
            seed_lead(self.db, days_ago=1)
        elif scenario_id == "data_quality":
            lead = seed_lead(self.db)
            seed_opportunity(self.db, lead, stage="won")
        elif scenario_id in ("owner_rejection", "owner_acceptance"):
            for _ in range(5):
                seed_won_deal(self.db, service="web_app", approved=1000, true_cost=900)

    def _seed_rec_for_decision(self) -> str:
        insight, _ = self.mem.save_insight(new_insight(
            type_="margin", category="margin", title="Low margin", summary="m",
            evidence={"metric": "m", "value": 0.1, "sample_size": 8},
            confidence="HIGH", severity="HIGH",
        ))
        rec = new_recommendation(
            insight_id=insight["insight_id"], type_="change_pricing", title="Review",
            problem="", evidence_ids=[insight["insight_id"]], proposed_action="Review",
            alternatives=[], expected_benefit="", expected_risk="", dependencies="",
            confidence="HIGH", requires_owner_approval=True,
        )
        return self.mem.save_recommendation(rec)

    def test_phase3g_scenarios(self):
        scenarios = json.loads((FIXTURES / "insights_scenarios.json").read_text())["scenarios"]
        for sc in scenarios:
            sid = sc["id"]
            with self.subTest(sid=sid):
                self._reset_services()
                self._seed(sid)
                summary = self.engine.run()
                insights = self.mem.list_insights()
                recs = self.mem.list_recommendations()
                expect = sc["expect"]

                if expect == "insight_recommendation":
                    self.assertGreater(summary["created"], 0, sid)
                    self.assertGreater(summary["recommendations"], 0, sid)
                elif expect == "review_not_repricing":
                    margin = [i for i in insights if i["type"] == "margin"]
                    self.assertTrue(margin, sid)
                    pricing_recs = [r for r in recs if r["type"] == "change_pricing"]
                    self.assertTrue(pricing_recs, sid)
                    for r in pricing_recs:
                        self.assertIn("Review", r["proposed_action"], sid)
                        self.assertNotIn("Raise price to", r["proposed_action"], sid)
                elif expect == "pricing_insight":
                    self.assertTrue(any(i["type"] == "pricing" for i in insights), sid)
                elif expect == "content_recommendation":
                    self.assertTrue(any(i["type"] == "content" for i in insights), sid)
                elif expect == "product_insight":
                    self.assertTrue(any(i["type"] == "support_recurrence" for i in insights), sid)
                elif expect == "ai_cost_insight":
                    self.assertTrue(any(i["type"] == "ai_cost" for i in insights), sid)
                elif expect == "capacity_warning":
                    self.assertTrue(any(i["type"] == "capacity" for i in insights), sid)
                    capacity_recs = [r for r in recs if r["type"] == "capacity"]
                    if capacity_recs:
                        self.assertTrue(capacity_recs[0]["requires_owner_approval"], sid)
                elif expect == "product_opportunity":
                    self.assertTrue(any(i["type"] == "saas_candidate" for i in insights), sid)
                elif expect == "insufficient":
                    # no executive recommendation for a 2-observation signal
                    for r in recs:
                        self.assertNotIn(r["type"],
                                         ("change_pricing", "change_offer", "change_policy"), sid)
                elif expect == "data_quality":
                    self.assertTrue(any(i["type"] == "data_quality" for i in insights), sid)
                elif expect == "no_change":
                    rid = self._seed_rec_for_decision()
                    v_before = self.db.execute("SELECT COUNT(*) AS c FROM pricing_snapshots").fetchone()["c"]
                    self.dss.reject(rid, decided_by="owner", reason="no")
                    self.assertEqual(self.mem.get_recommendation(rid)["status"], "rejected", sid)
                    v_after = self.db.execute("SELECT COUNT(*) AS c FROM pricing_snapshots").fetchone()["c"]
                    self.assertEqual(v_before, v_after, sid)
                    self.assertEqual(len(self.mem.list_decisions(rid)), 1, sid)
                elif expect == "decision_log_proposal":
                    rid = self._seed_rec_for_decision()
                    result = self.dss.accept(rid, decided_by="owner")
                    # Decision Log entry created
                    self.assertEqual(self.mem.list_decisions(rid)[0]["decision"], "accepted", sid)
                    # Approval request created; brain NOT mutated (no writer wired here)
                    self.assertIsNotNone(result["approval_id"], sid)
                    self.assertIsNone(result.get("brain_change_proposal"), sid)
                    rec = self.mem.get_recommendation(rid)
                    self.assertEqual(rec["status"], "accepted", sid)


if __name__ == "__main__":
    unittest.main()
