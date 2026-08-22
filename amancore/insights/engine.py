"""Insights Engine — orchestrates deterministic detectors into insights.

Data → Evidence → Insight → Recommendation → Risk/Policy → Owner Decision.
Functions calculate; AI (optional router) interprets; the Owner decides.
This engine CANNOT mutate business state: no pricing, no brain writes,
no sends, no CRM mutation.
"""

from __future__ import annotations

from ..analytics.service import AnalyticsService
from ..ids import new_id, utcnow
from .anomalies import materialized_anomaly
from .data_quality import DataQualityService
from .memory import InsightMemory
from .model import (
    build_evidence,
    confidence_from_samples,
    new_insight,
    severity_for,
)
from .opportunity import OpportunityDetector
from .optimizers import OptimizationAnalyzer
from .recommendations import RecommendationEngine
from .segments import SegmentAnalyzer
from .trends import classify_series


class InsightsEngine:
    def __init__(self, db, analytics=None, config=None, memory=None,
                 rec_engine=None, owner_alert=None, audit=None, dispatcher=None,
                 router=None):
        self.db = db
        self.analytics = analytics or AnalyticsService(db)
        self.config = config or {}
        self.memory = memory or InsightMemory(db)
        self.rec_engine = rec_engine or RecommendationEngine()
        self.owner_alert = owner_alert
        self.audit = audit
        self.dispatcher = dispatcher
        self.router = router
        self.optimizer = OptimizationAnalyzer(db, self.analytics)
        self.segments = SegmentAnalyzer(db, self.analytics)
        self.opportunities = OpportunityDetector(db, self.analytics, config)
        self.dq = DataQualityService(db)
        self.trend_cfg = self.config.get("trend", {})
        self.policy = self.config.get("insight_policy", {})
        self.anomaly_cfg = self.config.get("anomaly", {})
        self.capacity_cfg = self.config.get("capacity", {})

    # ---- public API -----------------------------------------------------
    def run(self, period_days: int = 7) -> dict:
        """Run all detectors, persist insights + recommendations (dedup), alert owner."""
        self.memory.expire_stale()
        candidates: list[dict] = []
        candidates += self._data_quality_candidates()
        candidates += self._trend_candidates(period_days)
        candidates += self._anomaly_candidates(period_days)
        candidates += self._margin_candidates()
        candidates += self._offer_candidates()
        candidates += self._funnel_candidates()
        candidates += self._content_candidates()
        candidates += self._support_candidates()
        candidates += self._ai_cost_candidates()
        candidates += self._capacity_candidates()
        candidates += self._opportunity_candidates()

        summary = {"created": 0, "updated": 0, "recommendations": 0, "alerts": 0,
                   "candidates": len(candidates)}
        for cand in candidates:
            insight = self._interpret(cand)
            saved, updated = self.memory.save_insight(insight)
            if updated:
                summary["updated"] += 1
            else:
                summary["created"] += 1
            self._emit("insight.updated" if updated else "insight.created", saved)
            # INSUFFICIENT_DATA => no executive recommendation (spec section 10)
            if saved["confidence"] != "INSUFFICIENT_DATA":
                rec = self.rec_engine.generate(saved)
                rid = self.memory.save_recommendation(rec)
                self.memory.update_insight(saved["insight_id"], recommendation_id=rid)
                summary["recommendations"] += 1
                self._emit("recommendation.created", {"recommendation_id": rid, "insight_id": saved["insight_id"]})
                if saved["severity"] in ("HIGH", "CRITICAL"):
                    self._alert_owner(saved, rec)
                    summary["alerts"] += 1
            elif saved["severity"] in ("HIGH", "CRITICAL"):
                self._alert_owner(saved, None)
                summary["alerts"] += 1
        return summary

    # ---- interpretation (optional LLM enrichment, never decisions) -------
    def _interpret(self, cand: dict) -> dict:
        if self.router is None:
            return cand
        from ..util import run_json

        data = run_json(
            self.router, "reasoning",
            f"Interpret this business insight evidence and summarize what matters "
            f"in one sentence (JSON: {{\"explanation\": \"...\"}}). "
            f"Evidence: {cand.get('evidence')}",
            default={},
        )
        if isinstance(data, dict) and data.get("explanation"):
            cand["summary"] = cand["summary"] + f" {data['explanation']}"
        return cand

    # ---- detectors ------------------------------------------------------
    def _data_quality_candidates(self) -> list[dict]:
        out = []
        for issue in self.dq.run_checks():
            if issue["affected_records"] == 0:
                continue
            sev = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}.get(issue["severity"], "LOW")
            out.append(new_insight(
                type_="data_quality",
                category="data_quality",
                title=f"Data quality: {issue['field']}",
                summary=f"{issue['problem']} — {issue['affected_records']} record(s) affected.",
                evidence=build_evidence(
                    source="data_quality", metric=issue["field"],
                    value=issue["affected_records"], comparison="count",
                    sample_size=issue["affected_records"],
                    caveats=issue["recommendation"],
                ),
                confidence="HIGH" if issue["affected_records"] >= 3 else "MEDIUM",
                severity=sev,
                metrics={"affected_records": issue["affected_records"]},
                fingerprint=f"dq:{issue['entity']}:{issue['field']}",
                related_entities=[issue["entity"]],
            ))
        return out

    def _series(self, table: str, column: str, cond: str = "", days: int = 7,
                value_col: str | None = None) -> list[float]:
        from datetime import datetime, timedelta, timezone

        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        sql = (f"SELECT date({column}) AS d, "
               f"{value_col if value_col else 'COUNT(*)'} AS v "
               f"FROM {table} WHERE {column} >= ? {cond} GROUP BY d ORDER BY d")
        rows = self.db.execute(sql, (start,)).fetchall()
        return [float(r["v"]) for r in rows]

    def _trend_candidates(self, days: int) -> list[dict]:
        out = []
        series_defs = [
            ("leads", "leads", "created_at", "", "acquisition", "acquisition", None),
            ("qualified leads", "leads", "created_at",
             "AND lead_stage IN ('qualified','hot')", "acquisition", "sales", None),
            ("opportunities", "opportunities", "created_at", "", "sales", "sales", None),
            ("won deals", "opportunities", "created_at",
             "AND stage IN ('won','closed_won')", "revenue", "sales", None),
            ("support cases", "support_cases", "created_at", "", "support", "support", None),
            ("content pieces", "content_items", "created_at", "", "content", "content", None),
            ("AI cost", "usage_records", "created_at", "", "ai_cost", "ai_cost",
             "COALESCE(SUM(estimated_cost),0)"),
        ]
        for label, table, col, cond, category, fp_cat, value_col in series_defs:
            series = self._series(table, col, cond, days, value_col)
            analysis = classify_series(series, self.trend_cfg)
            if analysis["trend"] is None:
                continue
            conf = confidence_from_samples(len(series), 0.9 if analysis["confidence"] == "HIGH" else 0.5, self.policy)
            out.append(new_insight(
                type_="trend",
                category=category,
                title=f"{label.capitalize()} trend: {analysis['trend']}",
                summary=f"{label.capitalize()} are {analysis['trend']} "
                        f"({analysis.get('change_pct', 0)*100:.0f}% change, latest={analysis.get('latest')}).",
                evidence=build_evidence(
                    source="trend", metric=label, value=analysis.get("latest"),
                    baseline=analysis.get("min"), comparison=analysis["trend"],
                    period=f"last {days}d", sample_size=len(series),
                    caveats="deterministic series comparison",
                ),
                confidence=conf,
                severity=severity_for(conf, None, is_risk=analysis["trend"] == "falling", policy=self.policy),
                metrics={"trend": analysis["trend"], "change_pct": analysis.get("change_pct"),
                         "series": series[-14:]},
                period=f"last {days}d",
                fingerprint=f"trend:{fp_cat}:{label}:{days}d",
            ))
        return out

    def _anomaly_candidates(self, days: int) -> list[dict]:
        out = []
        checks = [
            ("leads drop", "leads", "created_at", "", "acquisition", "low",
             "unusual drop in leads", None),
            ("support spike", "support_cases", "created_at", "", "support", "high",
             "unusual increase in support", None),
            ("AI cost spike", "usage_records", "created_at", "", "ai_cost", "high",
             "unusual AI cost", "COALESCE(SUM(estimated_cost),0)"),
        ]
        for label, table, col, cond, category, direction, problem, value_col in checks:
            series = self._series(table, col, cond, days, value_col)
            if len(series) < 2:
                continue
            today = series[-1]
            history = series[:-1]
            if not history:
                continue
            anomaly = materialized_anomaly(
                metric=label, value=today, history=history, config=self.anomaly_cfg,
                direction=direction,
                monetary_impact=today if category == "ai_cost" else None,
            )
            if anomaly is None:
                continue
            conf = confidence_from_samples(len(series), 0.9, self.policy)
            out.append(new_insight(
                type_="anomaly",
                category=category,
                title=f"Anomaly: {label}",
                summary=f"{problem}: latest {anomaly['value']:.2f} vs history mean "
                        f"{anomaly['history_mean']:.2f} (z={anomaly['z_score']}).",
                evidence=build_evidence(
                    source="anomaly", metric=label, value=anomaly["value"],
                    baseline=anomaly["history_mean"], comparison=f"z={anomaly['z_score']}",
                    period=f"last {days}d", sample_size=len(series),
                    caveats="z-score based",
                ),
                confidence=conf,
                severity=severity_for(conf, anomaly.get("monetary_impact"), is_risk=True, policy=self.policy),
                metrics=anomaly,
                period=f"last {days}d",
                fingerprint=f"anomaly:{category}:{label}:{days}d",
            ))
        return out

    def _margin_candidates(self) -> list[dict]:
        out = []
        for row in self.segments.margin_by("service"):
            margin = row["gross_margin"]
            if margin is None or row["deals"] == 0:
                continue
            if margin < 0.3:  # low margin threshold (deterministic, config-free note in caveats)
                conf = confidence_from_samples(row["deals"], 0.8, self.policy)
                out.append(new_insight(
                    type_="margin", category="margin",
                    title=f"Low margin: {row['segment']}",
                    summary=f"Service {row['segment']} gross margin is {margin*100:.0f}% "
                            f"(revenue {row['revenue']:.0f}, true cost {row['true_cost']:.0f}, {row['deals']} deals).",
                    evidence=build_evidence(
                        source="margin", metric="gross_margin", value=margin,
                        baseline=0.3, comparison="low", period="all-time",
                        sample_size=row["deals"], caveats="approved prices + internal true cost",
                    ),
                    confidence=conf,
                    severity=severity_for(conf, row["revenue"] - row["true_cost"], is_risk=True, policy=self.policy),
                    metrics=row,
                    segment=row["segment"],
                    fingerprint=f"margin:service:{row['segment']}",
                ))
        return out

    def _offer_candidates(self) -> list[dict]:
        out = []
        analysis = self.optimizer.offer_analysis()
        for offer in analysis["offers"]:
            if offer["count"] < self.policy.get("minimum_samples", 3):
                continue
            if offer.get("proposal_rate") is not None and offer["proposal_rate"] < 0.3:
                conf = confidence_from_samples(offer["count"], 0.7, self.policy)
                out.append(new_insight(
                    type_="offer", category="offer",
                    title=f"Offer rarely accepted: {offer['service']}",
                    summary=f"Service {offer['service']}: {offer['count']} opportunities, "
                            f"proposal rate {offer['proposal_rate']*100:.0f}%.",
                    evidence=build_evidence(
                        source="offer", metric="proposal_rate", value=offer["proposal_rate"],
                        baseline=0.3, comparison="low", sample_size=offer["count"],
                    ),
                    confidence=conf,
                    severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                    metrics=offer, segment=offer["service"],
                    fingerprint=f"offer:{offer['service']}:proposal_rate",
                ))
        objections = analysis["objections"]
        for obj, count in objections.items():
            if count >= 3:
                conf = confidence_from_samples(count, 0.7, self.policy)
                out.append(new_insight(
                    type_="pricing", category="pricing",
                    title=f"Frequent objection: {obj}",
                    summary=f"Objection '{obj}' recorded {count} time(s) across conversations.",
                    evidence=build_evidence(
                        source="conversations", metric="objection", value=count,
                        comparison="frequency", sample_size=count,
                    ),
                    confidence=conf,
                    severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                    metrics={"objection": obj, "count": count},
                    segment=obj,
                    fingerprint=f"pricing:objection:{obj}",
                ))
        return out

    def _funnel_candidates(self) -> list[dict]:
        out = []
        funnel = self.analytics.funnel()
        for c in funnel["conversions"]:
            if c["rate"] is None:
                continue
            if c["rate"] < 0.3:
                conf = confidence_from_samples(10, 0.7, self.policy)
                out.append(new_insight(
                    type_="sales_funnel", category="sales",
                    title=f"Weak conversion: {c['from']} → {c['to']}",
                    summary=f"Funnel conversion {c['from']} → {c['to']} is "
                            f"{c['rate']*100:.0f}% (threshold 30%).",
                    evidence=build_evidence(
                        source="funnel", metric=f"{c['from']}->{c['to']}", value=c["rate"],
                        baseline=0.3, comparison="low", sample_size=10,
                        caveats="counts are small at early stage",
                    ),
                    confidence=conf,
                    severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                    metrics=c,
                    fingerprint=f"funnel:{c['from']}->{c['to']}",
                ))
        return out

    def _content_candidates(self) -> list[dict]:
        out = []
        attr = self.optimizer.content_attribution()
        if len(attr) < 2:
            return out
        best = attr[0]
        if best["leads"] < self.policy.get("minimum_samples", 3):
            return out
        conf = confidence_from_samples(best["leads"], 0.7, self.policy)
        out.append(new_insight(
            type_="content", category="content",
            title=f"Content outperforms: {best['content_id']}",
            summary=f"Content {best['content_id']} drives {best['leads']} lead(s), "
                    f"{best['opportunities']} opportunity/ies, revenue {best['revenue']}.",
            evidence=build_evidence(
                source="content_attribution", metric="leads", value=best["leads"],
                comparison="top performer", sample_size=best["leads"],
            ),
            confidence=conf,
            severity=severity_for(conf, best["revenue"] or None, policy=self.policy),
            metrics=best, segment=best["content_id"],
            fingerprint=f"content:best:{best['content_id']}",
        ))
        return out

    def _support_candidates(self) -> list[dict]:
        out = []
        recurring = self.optimizer.recurring_issues(
            threshold=int(self.capacity_cfg.get("support_recurrence_threshold", 3))
        )
        for issue in recurring:
            conf = confidence_from_samples(issue["count"], 0.8, self.policy)
            out.append(new_insight(
                type_="support_recurrence", category="support",
                title=f"Recurring support issue: {issue['category']}",
                summary=f"Category '{issue['category']}' has {issue['count']} open/repeated case(s).",
                evidence=build_evidence(
                    source="support_cases", metric="recurrence", value=issue["count"],
                    comparison="repeat", sample_size=issue["count"],
                    caveats="open cases only",
                ),
                confidence=conf,
                severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                metrics=issue, segment=issue["category"],
                fingerprint=f"support:recurring:{issue['category']}",
            ))
        return out

    def _ai_cost_candidates(self) -> list[dict]:
        out = []
        analysis = self.optimizer.ai_cost_analysis()
        if analysis["pro_share"] is not None and analysis["pro_share"] > 0.6:
            conf = confidence_from_samples(max(5, int(self.analytics.ai_tokens()["value"] or 0) // 1000), 0.8, self.policy)
            out.append(new_insight(
                type_="ai_cost", category="ai_cost",
                title="Pro model usage unusually high",
                summary=f"Pro models are {analysis['pro_share']*100:.0f}% of AI cost "
                        f"(total {analysis['total_cost']:.2f}).",
                evidence=build_evidence(
                    source="usage_records", metric="pro_share", value=analysis["pro_share"],
                    baseline=0.6, comparison="high", sample_size=5,
                    caveats="routing config review — never downgrade high-risk tasks",
                ),
                confidence=conf,
                severity=severity_for(conf, analysis["total_cost"], is_risk=False, policy=self.policy),
                metrics=analysis, fingerprint="ai_cost:pro_share",
            ))
        return out

    def _capacity_candidates(self) -> list[dict]:
        out = []
        cap = self.optimizer.capacity_analysis()
        hours_cfg = float(self.capacity_cfg.get("founder_hours_per_month", 160))
        utilization_warning = float(self.capacity_cfg.get("utilization_warning", 0.8))
        active = cap["active_projects"]
        if active == 0:
            return out
        # upper-bound utilization: logged hours on active projects vs monthly capacity
        utilization = cap["hours_logged"] / hours_cfg if hours_cfg else 0.0
        if utilization >= utilization_warning:
            conf = confidence_from_samples(active, 0.8, self.policy)
            out.append(new_insight(
                type_="capacity", category="capacity",
                title="Capacity bottleneck",
                summary=f"Estimated utilization {utilization*100:.0f}% of founder capacity "
                        f"({active} active projects).",
                evidence=build_evidence(
                    source="projects", metric="utilization", value=round(utilization, 4),
                    baseline=utilization_warning, comparison="high", sample_size=active,
                    caveats="upper bound from cumulative logged hours; not a hiring decision",
                ),
                confidence=conf,
                severity=severity_for(conf, None, is_risk=True, policy=self.policy),
                metrics={**cap, "utilization": round(utilization, 4)},
                fingerprint="capacity:bottleneck",
            ))
        return out

    def _opportunity_candidates(self) -> list[dict]:
        out = []
        hot = self.opportunities.hot_leads_waiting()
        if hot:
            conf = confidence_from_samples(len(hot), 0.9, self.policy)
            out.append(new_insight(
                type_="opportunity", category="sales",
                title=f"{len(hot)} hot lead(s) waiting",
                summary=f"{len(hot)} hot lead(s) have no recent follow-up.",
                evidence=build_evidence(
                    source="leads", metric="hot_waiting", value=len(hot),
                    comparison="threshold", sample_size=len(hot),
                ),
                confidence=conf,
                severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                metrics={"hot_waiting": len(hot), "leads": [h["lead_id"] for h in hot[:10]]},
                fingerprint="opportunity:hot_waiting",
                related_entities=[h["lead_id"] for h in hot],
            ))
        high_value = self.opportunities.high_value_opportunities()
        if high_value:
            conf = confidence_from_samples(len(high_value), 0.8, self.policy)
            value = sum(h["estimated_value"] or 0 for h in high_value)
            out.append(new_insight(
                type_="opportunity", category="revenue",
                title=f"{len(high_value)} high-value opportunity/ies pending",
                summary=f"Open opportunities worth ~{value:.0f} in total are pending.",
                evidence=build_evidence(
                    source="opportunities", metric="pipeline_value", value=value,
                    comparison="pending", sample_size=len(high_value),
                    caveats="estimated values; approved price governs revenue",
                ),
                confidence=conf,
                severity=severity_for(conf, value, policy=self.policy),
                metrics={"pipeline_value": value, "count": len(high_value)},
                fingerprint="opportunity:high_value",
                related_entities=[o["opportunity_id"] for o in high_value],
            ))
        # SaaS / product candidates
        for cand in self.opportunities.saas_candidates():
            out.append(new_insight(
                type_="saas_candidate", category="product",
                title=f"Product candidate: {cand['problem']}",
                summary=f"The problem '{cand['problem']}' repeats across {cand['frequency']} case(s) — "
                        f"potential product opportunity (owner decides, no auto-build).",
                evidence=build_evidence(
                    source="support_cases", metric="recurrence", value=cand["frequency"],
                    comparison="repeat", sample_size=cand["frequency"],
                    caveats="no willingness-to-pay signal yet",
                ),
                confidence=cand["confidence"],
                severity=severity_for(cand["confidence"], None, is_risk=False, policy=self.policy),
                metrics=cand, segment=cand["problem"],
                fingerprint=f"saas:{cand['problem']}",
            ))
        # market scores
        for m in self.opportunities.market_opportunity_score():
            if m["sample_size"] < self.policy.get("minimum_samples", 3):
                continue
            conf = confidence_from_samples(m["sample_size"], 0.6, self.policy)
            out.append(new_insight(
                type_="market", category="market",
                title=f"Market signal: {m['market']}",
                summary=f"Market {m['market']}: {m['leads']} leads, {m['won']} won, "
                        f"opportunity score {m['score']}.",
                evidence=build_evidence(
                    source="leads", metric="market_score", value=m["score"],
                    comparison="across markets", sample_size=m["sample_size"],
                    caveats="score is informational; market selection is owner-only",
                ),
                confidence=conf,
                severity=severity_for(conf, None, is_risk=False, policy=self.policy),
                metrics=m, segment=m["market"],
                fingerprint=f"market:{m['market']}",
            ))
        return out

    # ---- helpers ---------------------------------------------------------
    def _alert_owner(self, insight: dict, rec: dict | None) -> None:
        if self.owner_alert is None:
            return
        rec_type = rec["type"] if rec else "observe"
        msg = (
            f"INSIGHT [{insight['severity']}] {insight['title']} | "
            f"Why it matters: {insight['summary']} | "
            f"Evidence: {insight['evidence'].get('metric')}={insight['evidence'].get('value')} "
            f"(n={insight['evidence'].get('sample_size')}) | "
            f"Recommendation: {rec['proposed_action'] if rec else 'none (insufficient data)'} | "
            f"Risk: {rec['expected_risk'] if rec else 'none'} | "
            f"Decision required: {rec['required_decision'] if rec else 'collect more data'}"
        )
        self.owner_alert("critical" if insight["severity"] == "CRITICAL" else "high",
                         msg, insight["insight_id"])

    def _emit(self, event_type: str, data: dict) -> None:
        if self.dispatcher is None:
            return
        from ..services.events import CanonicalEvent

        self.dispatcher.publish(CanonicalEvent(
            event_id=new_id(), event_type=event_type, timestamp=utcnow(),
            source="insights", actor_type="system", payload=dict(data),
        ))
