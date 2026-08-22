"""AmanCore Foundation health/readiness check (local)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .business_brain.store import BrainStore
from .business_brain.validator import validate_brain
from .config import Config, load_config
from .crm.service import CRMService
from .routing.providers import build_providers
from .routing.router import ModelRouter
from .services.audit import AuditService
from .services.events import CanonicalEvent, EventDispatcher
from .services.policy import PolicyEngine
from .services.risk import RiskEngine
from .storage.db import open_database


def _check(name: str, fn) -> tuple[str, str]:
    try:
        detail = fn()
        return "PASS", str(detail) if detail else ""
    except Exception as exc:  # noqa: BLE001
        return "FAIL", f"{type(exc).__name__}: {exc}"


def run_health_checks(root: Path) -> dict[str, tuple[str, str]]:
    results: dict[str, tuple[str, str]] = {}

    # configuration
    cfg: Config | None = None

    def _load_cfg() -> Config:
        nonlocal cfg
        cfg = load_config(root)
        return cfg

    results["configuration"] = _check("configuration", lambda: (_load_cfg(), f"env={cfg.app.get('env')}")[1])

    # database
    db = None

    def _open_db():
        nonlocal db
        cfg2 = cfg or load_config(root)
        schema = root / "amancore" / "storage" / "schema.sql"
        db = open_database(cfg2.database_path, schema)
        db.execute("SELECT COUNT(*) AS c FROM leads").fetchone()
        return cfg2.database_path

    results["database"] = _check("database", _open_db)

    # business brain
    store = BrainStore(root / "amancore" / "business_brain")
    results["business_brain"] = _check("business_brain", lambda: _bb(store))

    # crm
    results["crm"] = _check("crm", lambda: _crm(db))

    # events
    results["events"] = _check("events", _events)

    # policy
    results["policy_engine"] = _check("policy_engine", lambda: _policy(store))

    # risk
    results["risk_engine"] = _check("risk_engine", _risk)

    # approvals
    results["approval_service"] = _check("approval_service", lambda: _approvals(db))

    # audit
    results["audit"] = _check("audit", lambda: _audit(db))

    # model router
    results["model_router"] = _check("model_router", lambda: _router(cfg or load_config(root)))

    # security
    results["security"] = _check("security", lambda: _security(root))

    # channels (Phase 3E — mock-mode configuration state, not production readiness)
    cfg3 = cfg or load_config(root)
    results["whatsapp_config"] = _check("whatsapp_config", lambda: _whatsapp_config(cfg3))
    results["whatsapp_webhook"] = _check("whatsapp_webhook", lambda: _whatsapp_webhook(cfg3))
    results["channel_policy"] = _check("channel_policy", lambda: _channel_policy(store))
    results["message_outbox"] = _check("message_outbox", lambda: _message_outbox(db))
    results["website_intake"] = _check("website_intake", lambda: _website_intake(db))
    results["sales_integration"] = _check("sales_integration", lambda: _sales_integration(store))
    results["pricing_snapshot"] = _check("pricing_snapshot", lambda: _pricing_snapshot(db))
    results["owner_alert"] = _check("owner_alert", lambda: _owner_alert())

    # Phase 3F — support, analytics, production gate (informational: mock-safe)
    results["support_cases"] = _check("support_cases", lambda: _support_cases(db))
    results["analytics"] = _check("analytics", lambda: _analytics(db))
    results["production_gate"] = _check("production_gate", lambda: _production_gate(cfg3))

    if db is not None:
        db.close()
    return results


def _bb(store: BrainStore) -> str:
    version, data = store.current()
    errors = validate_brain(data)
    if errors:
        raise RuntimeError("; ".join(errors))
    return f"v{version} valid"


def _crm(db) -> str:
    crm = CRMService(db)
    n = db.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
    return f"leads table ok ({n} rows)"


def _events() -> str:
    d = EventDispatcher()
    seen: list[str] = []
    d.subscribe("lead.created", lambda e: seen.append(e.event_id))
    ev = CanonicalEvent(
        event_id="health-event", event_type="lead.created", timestamp="2026-01-01T00:00:00+00:00"
    )
    d.publish(ev)
    return f"dispatched={len(seen)}"


def _policy(store: BrainStore) -> str:
    _, brain = store.current()
    d = PolicyEngine().evaluate(brain, "lead.created", "low")
    return f"decision={d.action}"


def _risk() -> str:
    r = RiskEngine()
    return f"price.calculated={r.classify('price.calculated')}, contract={r.classify('deal.won', action='contract')}"


def _approvals(db) -> str:
    n = db.execute("SELECT COUNT(*) AS c FROM approvals").fetchone()["c"]
    return f"approvals table ok ({n} rows)"


def _audit(db) -> str:
    a = AuditService(db)
    a.record(action="health.check", resource="health", result="ok")
    return f"audit append ok ({a.count()} total)"


def _router(cfg: Config) -> str:
    providers = build_providers(cfg.models)
    router = ModelRouter(cfg.models, providers)
    order = router._order("strategy")
    return f"strategy order={order}"


def _security(root: Path) -> str:
    gi = root / ".gitignore"
    if not gi.exists():
        raise RuntimeError(".gitignore missing")
    text = gi.read_text(encoding="utf-8")
    if ".env" not in text:
        raise RuntimeError(".gitignore does not exclude .env")
    return ".env excluded"


def _whatsapp_config(cfg: Config) -> str:
    w = cfg.channels.get("whatsapp", {})
    mode = w.get("mode", "mock")
    if mode not in ("mock", "sandbox", "production"):
        raise RuntimeError(f"invalid whatsapp mode: {mode}")
    return f"mode={mode} api_version={w.get('api_version')}"


def _whatsapp_webhook(cfg: Config) -> str:
    from .channels.whatsapp import WhatsAppAdapter

    w = cfg.channels.get("whatsapp", {})
    adapter = WhatsAppAdapter(w)
    result = adapter.verify_webhook("subscribe", w.get("verify_token", ""), "challenge")
    if w.get("mode") == "mock":
        return "mock webhook verifier available (production pending verification)"
    if not result.get("verified"):
        raise RuntimeError("verify token not configured")
    return "webhook verified"


def _channel_policy(store) -> str:
    from .channels.policy import ChannelPolicyEngine

    policy = ChannelPolicyEngine(store)
    return f"send(text)={policy.evaluate_send('whatsapp', 'text')}"


def _message_outbox(db) -> str:
    from .channels.outbox import MessageOutbox

    outbox = MessageOutbox(db)
    return f"outbox counts={outbox.counts()}"


def _website_intake(db) -> str:
    n = db.execute("SELECT COUNT(*) AS c FROM intake_events").fetchone()["c"]
    return f"intake_events table ok ({n} rows)"


def _sales_integration(store) -> str:
    from .sales.qualification import QualificationEngine

    q = QualificationEngine().qualify({"facts": {"problem": "x"}}, {}, {"overall_fit": "medium"})
    return f"sales ready={not q['decision_readiness']}"


def _pricing_snapshot(db) -> str:
    n = db.execute("SELECT COUNT(*) AS c FROM pricing_snapshots").fetchone()["c"]
    return f"pricing_snapshots table ok ({n} rows)"


def _owner_alert() -> str:
    from .services.owner_alert import send_owner_alert

    send_owner_alert("info", "health check")
    return "alert sink ok"


def _support_cases(db) -> str:
    from .support.cases import SupportCaseStore

    store = SupportCaseStore(db)
    return f"support_cases table ok ({store.counts()})"


def _analytics(db) -> str:
    from .analytics.service import AnalyticsService

    svc = AnalyticsService(db)
    return f"kpis read-only ok (leads={svc.leads_total()['value']}, margin={svc.gross_margin()['value']})"


def _production_gate(cfg: Config) -> str:
    from .production.gate import ProductionGateService

    production = dict(cfg.production)
    report = ProductionGateService(production).check()
    if report["production_enabled"]:
        raise RuntimeError("production_enabled must be false in this environment")
    return f"verdict={report['verdict']} (safe: production disabled, mode={report['mode']})"


def print_health_report(results: dict[str, tuple[str, str]]) -> int:
    print("AMANCORE FOUNDATION HEALTH")
    print("-" * 40)
    failed = 0
    for name, (status, detail) in results.items():
        print(f"{name:<22} {status:<6} {detail}")
        if status != "PASS":
            failed += 1
    print("-" * 40)
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1
