"""Test seeding helpers for insights — dedicated test DB only, never production."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from amancore.ids import new_id, utcnow


def _ts(days_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def seed_lead(db, *, days_ago=0, source="whatsapp", stage="nurture", score=0,
              market="indonesia", name=None, company=None) -> str:
    lead_id = new_id()
    ts = _ts(days_ago)
    db.execute(
        "INSERT INTO leads (lead_id, status, lead_score, lead_stage, source_channel, "
        " market, name, company, created_at, updated_at) VALUES (?, 'new', ?, ?, ?, ?, ?, ?, ?, ?)",
        (lead_id, score, stage, source, market, name, company, ts, ts),
    )
    db.commit()
    return lead_id


def seed_opportunity(db, lead_id, *, service="website_standard", stage="offer_recommended",
                     days_ago=0, estimated_value=None, reason=None) -> str:
    opp_id = new_id()
    ts = _ts(days_ago)
    db.execute(
        "INSERT INTO opportunities (opportunity_id, lead_id, service, stage, estimated_value, "
        " reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (opp_id, lead_id, service, stage, estimated_value, reason, ts, ts),
    )
    db.commit()
    return opp_id


def seed_snapshot(db, opp_id, *, approved=1000.0, true_cost=400.0, days_ago=0) -> str:
    import json

    snap_id = new_id()
    ts = _ts(days_ago)
    calc = json.dumps({"currency": "USD", "true_cost": true_cost, "pricing_policy_version": "v1"})
    db.execute(
        "INSERT INTO pricing_snapshots (snapshot_id, opportunity_id, business_brain_version, "
        " calculated_result, approved_price, currency, approved_by, approved_at, created_at) "
        "VALUES (?, ?, 1, ?, ?, 'USD', 'owner', ?, ?)",
        (snap_id, opp_id, calc, approved, ts, ts),
    )
    db.commit()
    return snap_id


def seed_won_deal(db, *, service="website_standard", approved=1000.0, true_cost=400.0,
                  source="whatsapp", market="indonesia", days_ago=0) -> str:
    lead_id = seed_lead(db, days_ago=days_ago, source=source, stage="hot", score=75, market=market)
    opp_id = seed_opportunity(db, lead_id, service=service, stage="won", days_ago=days_ago,
                              estimated_value=approved)
    seed_snapshot(db, opp_id, approved=approved, true_cost=true_cost, days_ago=days_ago)
    return lead_id


def seed_support_case(db, *, category="technical_support", priority="MEDIUM",
                      status="open", days_ago=0, customer_id=None, lead_id=None) -> str:
    case_id = new_id()
    ts = _ts(days_ago)
    db.execute(
        "INSERT INTO support_cases (case_id, customer_id, lead_id, category, priority, status, "
        " summary, escalated, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (case_id, customer_id, lead_id, category, priority, status, "test case", ts, ts),
    )
    db.commit()
    return case_id


def seed_usage(db, *, model="deepseek-v4-pro", task="strategy", cost=0.5, tokens=1000,
               status="ok", days_ago=0) -> None:
    db.execute(
        "INSERT INTO usage_records (request_id, provider, model, task_class, input_tokens, "
        " output_tokens, estimated_cost, latency_ms, status, created_at) "
        "VALUES (?, 'deepseek', ?, ?, 500, ?, ?, 200, ?, ?)",
        (new_id(), model, task, tokens - 500, cost, status, _ts(days_ago)),
    )
    db.commit()


def seed_project(db, *, customer_id=None, status="active", hours=10.0, days_ago=0) -> str:
    project_id = new_id()
    ts = _ts(days_ago)
    db.execute(
        "INSERT INTO projects (project_id, customer_id, service, status, hours_logged, "
        " created_at, updated_at) VALUES (?, ?, 'website_standard', ?, ?, ?, ?)",
        (project_id, customer_id, status, hours, ts, ts),
    )
    db.commit()
    return project_id


def seed_content(db, *, content_id="c-1", topic="restaurant websites", status="approved",
                 days_ago=0) -> None:
    ts = _ts(days_ago)
    db.execute(
        "INSERT INTO content_items (content_id, status, content_type, topic, created_at, updated_at) "
        "VALUES (?, ?, 'article', ?, ?, ?)",
        (content_id, status, topic, ts, ts),
    )
    db.commit()


def seed_care_plan(db, *, customer_id=None, tier="basic", price=200.0, cycle="monthly",
                   status="active") -> str:
    cpid = new_id()
    ts = utcnow()
    db.execute(
        "INSERT INTO care_plans (care_plan_id, customer_id, plan_tier, billing_cycle, price, "
        " status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cpid, customer_id, tier, cycle, price, status, ts, ts),
    )
    db.commit()
    return cpid
