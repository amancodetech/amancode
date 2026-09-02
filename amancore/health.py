"""AmanCode Foundation health/readiness check (local)."""

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

    # channels — generic per-channel registration (adapter-driven);
    # unconfigured channels are skipped, never silently "pass"
    cfg3 = cfg or load_config(root)
    for _ch in ("whatsapp", "telegram", "facebook", "instagram"):
        if not cfg3.channels.get(_ch):
            continue
        results[f"channel_config:{_ch}"] = _check(
            f"channel_config:{_ch}", lambda ch=_ch: _channel_config(cfg3, ch))
        results[f"channel_webhook:{_ch}"] = _check(
            f"channel_webhook:{_ch}", lambda ch=_ch: _channel_webhook(cfg3, ch))
        # Bridge migration (owner spec §33): distinct process/session states —
        # only relevant when the channel actually resolves to mode: bridge
        results[f"bridge_process:{_ch}"] = _check(
            f"bridge_process:{_ch}",
            lambda ch=_ch: _bridge_state(cfg3, ch, want="process"))
        results[f"bridge_session:{_ch}"] = _check(
            f"bridge_session:{_ch}",
            lambda ch=_ch: _bridge_state(cfg3, ch, want="session"))
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

    # Phase 3G — insights engine (read-only smoke)
    results["insights"] = _check("insights", lambda: _insights(cfg3, db))

    # Phase 3H — operations
    results["scheduler"] = _check("scheduler", lambda: _scheduler(cfg3, db))
    results["alerts"] = _check("alerts", lambda: _alerts(db))
    results["backups"] = _check("backups", lambda: _backups(db))
    results["incidents"] = _check("incidents", lambda: _incidents(db))
    results["alert_transport"] = _check("alert_transport", lambda: _alert_transport(cfg3))

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


def _channel_config(cfg: Config, channel: str) -> str:
    """Generic per-channel configuration check — valid modes are universal,
    provider details stay inside the channel's own config block."""
    w = cfg.channels.get(channel, {})
    mode = w.get("mode", "mock")
    if mode not in ("mock", "sandbox", "production", "bridge"):
        raise RuntimeError(f"invalid {channel} mode: {mode}")
    extra = f" transport={w.get('bridge', {}).get('transport')}" \
        if mode == "bridge" else ""
    shadow = " shadow=ON" if (w.get("bridge") or {}).get("shadow") else ""
    return (f"mode={mode}{extra}{shadow}"
            + (f" api_version={w.get('api_version')}"
               if w.get("api_version") else ""))


def _bridge_state(cfg: Config, channel: str, want: str) -> str:
    """Bridge process/session health (owner spec §33) — states are DISTINCT:
    process UP/DOWN and session CONNECTED/AUTH_REQUIRED/... never collapse
    into one 'bridge down'. Skips (passes inertly) for non-bridge modes."""
    from .channels.provider_resolver import resolve_channel_config
    from .channels.bridge_transport import bridge_health_probe

    block = cfg.channels.get(channel, {})
    if block.get("mode") != "bridge":
        return "skipped (mode != bridge)"
    resolved = resolve_channel_config(channel, cfg.channels,
                                      cfg.production.get("environment") or {})
    if resolved is None:
        raise RuntimeError(f"channel '{channel}' disabled but mode=bridge")
    state = bridge_health_probe(resolved)
    if want == "process":
        if state["process"] != "UP":
            raise RuntimeError(f"bridge process DOWN: {state['detail']}")
        return f"bridge UP ({state['detail']})"
    if state["process"] != "UP":
        raise RuntimeError(f"session unknown — bridge process DOWN: "
                           f"{state['detail']}")
    session = state["session"]
    if session == "AUTH_REQUIRED":
        raise RuntimeError("session AUTH_REQUIRED — re-pair the bridge device")
    if session == "CONNECTED":
        return "session CONNECTED"
    if session == "UNKNOWN":
        raise RuntimeError("session state UNKNOWN: bridge up but no session report")
    return f"session {session}"


def _channel_webhook(cfg: Config, channel: str) -> str:
    import os as _os

    from .ops.scheduler_adapter import build_probe_adapter

    w = cfg.channels.get(channel, {})
    try:
        adapter = build_probe_adapter(channel, w)
    except KeyError:
        raise RuntimeError(f"channel '{channel}' has no registered adapter")
    # adapter-owned probe (channels without a Meta-style GET handshake)
    probe = getattr(adapter, "health_probe", None)
    if callable(probe):
        return probe()
    # verify against the CONFIGURED env token (verify_token_env), not a raw
    # yaml value — the raw `verify_token` key never carries the secret
    token_env = w.get("verify_token_env", "META_VERIFY_TOKEN")
    result = adapter.verify_webhook(
        "subscribe", _os.environ.get(token_env, ""), "challenge")
    # judge by the RESOLVED adapter mode (raw blocks say 'production' while
    # the resolver keeps them mock until the audited overlay flips)
    mode = (getattr(adapter, "config", {}) or {}).get("mode", "mock")
    if mode == "mock":
        return "mock webhook verifier available (production pending verification)"
    if not result.get("verified"):
        raise RuntimeError(f"verify token not configured (env {token_env})")
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
    env = cfg.production.get("environment", {})
    if report["production_enabled"]:
        # Enabled state is valid only when owner-approved enablement left a
        # consistent configuration (mode=production). Enablement itself is
        # audited in production.enablement.
        mode = env.get("mode")
        if mode != "production":
            raise RuntimeError(
                f"inconsistent production state: enabled but mode={mode}"
            )
        return (
            f"verdict=ENABLED (mode=production, audited; "
            f"disable via production-disable)"
        )
    return f"verdict={report['verdict']} (safe: production disabled, mode={report['mode']})"


def _insights(cfg: Config, db) -> str:
    from .analytics.service import AnalyticsService
    from .insights.engine import InsightsEngine

    analytics = AnalyticsService(db, config=cfg.analytics)
    engine = InsightsEngine(db, analytics=analytics, config=cfg.insights)
    summary = engine.run(period_days=7)
    return f"engine ok (created={summary['created']}, updated={summary['updated']}, recs={summary['recommendations']})"


def _scheduler(cfg: Config, db) -> str:
    from .ops.jobs import JobStore
    from .ops.scheduler import cron_matches

    store = JobStore(db, config=cfg.scheduler)
    if not cron_matches("* * * * *"):
        raise RuntimeError("cron matcher broken")
    return f"jobs ok ({store.counts()})"


def _alerts(db) -> str:
    from .ops.alerts import AlertStore

    store = AlertStore(db)
    return f"alerts table ok ({store.counts()})"


def _backups(db) -> str:
    from .ops.backup import BackupService
    from .ops.recovery import RecoveryService
    from .ops.startup import StartupService

    latest = BackupService(db, Path(".").resolve()).latest_verified_database()
    return f"backups table ok (latest_verified={latest['backup_id'][:8] if latest else 'NONE'})"


def _incidents(db) -> str:
    from .ops.incidents import IncidentService

    open_count = len(IncidentService(db).list(status="open"))
    return f"incidents table ok (open={open_count})"


def _alert_transport(cfg: Config) -> str:
    from .ops.alerts import transport_status

    return transport_status(cfg.scheduler.get("alert", {}))


def print_health_report(results: dict[str, tuple[str, str]]) -> int:
    print("AMANCODE FOUNDATION HEALTH")
    print("-" * 40)
    failed = 0
    for name, (status, detail) in results.items():
        print(f"{name:<22} {status:<6} {detail}")
        if status != "PASS":
            failed += 1
    print("-" * 40)
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1
