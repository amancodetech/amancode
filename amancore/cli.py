"""AmanCore CLI — local operator commands.

Usage:  python -m amancore.cli <command>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _health(args) -> int:
    from .health import print_health_report, run_health_checks

    return print_health_report(run_health_checks(ROOT))


def _test(args) -> int:
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-t", str(ROOT)]
    )


def _brain_validate(args) -> int:
    from .business_brain.store import BrainStore
    from .business_brain.validator import validate_brain

    store = BrainStore(ROOT / "amancore" / "business_brain")
    version, data = store.current()
    errors = validate_brain(data)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print(f"Business Brain v{version}: valid")
    return 0


def _brain_versions(args) -> int:
    from .business_brain.store import BrainStore

    store = BrainStore(ROOT / "amancore" / "business_brain")
    for v in store.versions():
        print(f"v{v['version']:<4} {v['approval_status']:<10} {v['reason']} (by {v['created_by']})")
    return 0


def _audit_recent(args) -> int:
    from .config import load_config
    from .services.audit import AuditService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    audit = AuditService(db)
    for e in audit.query(limit=args.n):
        print(f"{e['timestamp']}  {e['action']:<30} {e['resource']}  {e.get('result','')}")
    db.close()
    return 0


def _config_check(args) -> int:
    from .config import load_config

    cfg = load_config(ROOT)
    print(f"env          : {cfg.app.get('env')}")
    print(f"database_path: {cfg.database_path}")
    print(f"shadow_rate  : {cfg.shadow_rate}")
    print(f"markets      : {list(cfg.pricing.get('market_multiplier', {}).keys())}")
    return 0


def _production_check(args) -> int:
    import json

    from .config import load_config
    from .production.gate import ProductionGateService

    cfg = load_config(ROOT)
    production = dict(cfg.production)
    production["_root"] = ROOT
    gate = ProductionGateService(production)
    report = gate.check(run_health=True)
    print("AMANCORE PRODUCTION CHECK")
    print("-" * 40)
    print(f"verdict                 : {report['verdict']}")
    print(f"production_enabled      : {report['production_enabled']}")
    print(f"mode                    : {report['mode']}")
    print(f"official verification   : {report['official_verification_status']}")
    print("-" * 40)
    for g in report["gates"]:
        print(f"{g['gate']:<32} {g['status']}")
    print("-" * 40)
    print(f"RESULT: {report['verdict']}")
    return 0 if report["verdict"] != "NOT_READY" else 2


def _production_enable(args) -> int:
    import json

    from .config import load_config
    from .errors import ProductionNotEnabledError
    from .production.enablement import (
        ProductionEnablementError,
        ProductionEnablementService,
    )
    from .production.gate import ProductionGateService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    production = dict(cfg.production)
    production["_root"] = ROOT
    gate_report = ProductionGateService(production).check(run_health=True)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        svc = ProductionEnablementService(ROOT / "configs" / "production.yaml", db=db)
        result = svc.enable(gate_report, args.confirm, actor=args.actor, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProductionEnablementError, ProductionNotEnabledError) as exc:
        print(f"PRODUCTION ENABLE REFUSED: {exc}")
        return 2
    finally:
        db.close()


def _production_disable(args) -> int:
    import json

    from .config import load_config
    from .production.enablement import ProductionEnablementService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        svc = ProductionEnablementService(ROOT / "configs" / "production.yaml", db=db)
        result = svc.disable(actor=args.actor, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def _analytics(args) -> int:
    import json

    from .analytics.alerts import AlertService
    from .analytics.service import AnalyticsService
    from .config import load_config
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    svc = AnalyticsService(db, config=cfg.analytics)
    try:
        if args.sub == "kpis":
            kpis = [
                svc.leads_total(), svc.engaged_leads(), svc.qualified_leads(), svc.hot_leads(),
                svc.opportunities(), svc.proposals_approved(), svc.won(), svc.lost(),
                svc.close_rate(), svc.avg_deal_value(), svc.revenue(), svc.true_cost(),
                svc.gross_margin(), svc.mrr(), svc.ai_cost(), svc.support_cases(),
                svc.support_open(), svc.support_escalations(),
            ]
            print(json.dumps([{k: v for k, v in k.items() if k != "name"} for k in kpis], ensure_ascii=False, indent=2))
        elif args.sub == "funnel":
            print(json.dumps(svc.funnel(), ensure_ascii=False, indent=2))
        elif args.sub == "attribution":
            print(json.dumps({
                "leads": svc.attribution(args.by),
                "revenue": svc.revenue_attribution(args.by),
            }, ensure_ascii=False, indent=2))
        elif args.sub == "report":
            date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if args.period == "daily":
                report = svc.report_daily(date)
            elif args.period == "weekly":
                report = svc.report_weekly(date)
            else:
                report = svc.report_monthly(date)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.sub == "alerts":
            alerts = AlertService(db, config=cfg.alerts).check_all()
            print(json.dumps(alerts, ensure_ascii=False, indent=2) if alerts else "NO ACTIVE ALERTS")
        else:
            return 1
        return 0
    finally:
        db.close()


def _support(args) -> int:
    from .config import load_config
    from .storage.db import open_database
    from .support.cases import SupportCaseStore

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        store = SupportCaseStore(db)
        cases = store.list(status=args.status, limit=args.n)
        if not cases:
            print("NO SUPPORT CASES")
            return 0
        for c in cases:
            print(f"{c['case_id'][:8]}  {c['priority']:<8} {c['status']:<14} {c['category']:<18} {c['summary'][:60]}")
        return 0
    finally:
        db.close()


def _insights(args) -> int:
    import json

    from .analytics.service import AnalyticsService
    from .config import load_config
    from .insights.decisions import DecisionSupportService
    from .insights.engine import InsightsEngine
    from .insights.memory import InsightMemory
    from .insights.reports import InsightReports
    from .services.approvals import ApprovalService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        analytics = AnalyticsService(db, config=cfg.analytics)
        memory = InsightMemory(db)
        if args.sub == "list":
            rows = memory.list_insights(status=args.status, category=args.category, limit=args.n)
            if not rows:
                print("NO INSIGHTS")
            for i in rows:
                print(f"{i['insight_id'][:8]}  {i['severity']:<8} {i['confidence']:<16} "
                      f"{i['type']:<20} {i['title']}")
        elif args.sub == "review":
            engine = InsightsEngine(db, analytics=analytics, config=cfg.insights)
            summary = engine.run(period_days=args.period_days)
            print(json.dumps(summary, indent=2))
        elif args.sub == "recommendations":
            rows = memory.list_recommendations(status=args.status, limit=args.n)
            if not rows:
                print("NO RECOMMENDATIONS")
            for r in rows:
                print(f"{r['recommendation_id'][:8]}  {r['type']:<18} {r['status']:<12} "
                      f"approval={'Y' if r['requires_owner_approval'] else 'N'}  {r['title']}")
        elif args.sub == "report":
            reports = InsightReports(db, analytics, memory)
            if args.period == "daily":
                report = reports.daily_brief(args.date)
            elif args.period == "weekly":
                report = reports.weekly_review()
            else:
                report = reports.monthly_review()
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.sub == "data-quality":
            from .insights.data_quality import DataQualityService

            issues = DataQualityService(db).run_checks()
            print(json.dumps(issues, indent=2) if issues else "NO DATA QUALITY ISSUES")
        elif args.sub == "decide":
            dss = DecisionSupportService(
                db, memory=memory, approval_service=ApprovalService(db)
            )
            if args.decision == "accept":
                result = dss.accept(args.id, decided_by=args.by, reason=args.reason)
            elif args.decision == "reject":
                result = dss.reject(args.id, decided_by=args.by, reason=args.reason)
            else:
                result = dss.defer(args.id, decided_by=args.by, reason=args.reason)
            print(json.dumps(result, indent=2))
        else:
            return 1
        return 0
    finally:
        db.close()


def _status(args) -> int:
    import json

    from .config import load_config
    from .ops.monitoring import MonitoringService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        print(json.dumps(MonitoringService(db, ROOT).status(), ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def _jobs(args) -> int:
    import json

    from .config import load_config
    from .ops.jobs import JobRunner, JobStore
    from .ops.registry import JobRegistry
    from .ops.scheduler import SchedulerRuntime
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        store = JobStore(db, config=cfg.scheduler)
        if args.sub == "status":
            print(json.dumps(store.counts(), indent=2))
            for j in store.list(status=args.status, limit=args.n):
                print(f"{j['job_id'][:8]}  {j['type']:<20} {j['status']:<10} "
                      f"attempts={j['attempts']}  {(j.get('error') or '')[:60]}")
        elif args.sub == "run":
            handlers = JobRegistry(db, cfg, ROOT).handlers()
            runner = JobRunner(store, handlers, worker_id="cli")
            job_id = store.enqueue(args.job, idempotency_key=f"cli:{args.job}")
            result = runner.run_job(store.get(job_id))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.sub == "tick":
            runtime = SchedulerRuntime(store, JobRunner(store, JobRegistry(db, cfg, ROOT).handlers()), cfg.scheduler)
            print(json.dumps(runtime.run_once(), ensure_ascii=False, indent=2))
        elif args.sub == "loop":
            from .log import setup_logging

            setup_logging()
            runtime = SchedulerRuntime(store, JobRunner(store, JobRegistry(db, cfg, ROOT).handlers(), worker_id="scheduler"), cfg.scheduler)
            print("amancore scheduler loop started (ctrl-c / SIGTERM for graceful stop)", flush=True)
            runtime.run_loop()
            return 0
        else:
            return 1
        return 0
    finally:
        db.close()


def _backup(args) -> int:
    import json

    from .config import load_config
    from .ops.backup import BackupService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        svc = BackupService(db, ROOT)
        if args.sub == "create":
            print(json.dumps(svc.create_backup(), ensure_ascii=False, indent=2))
        elif args.sub == "verify":
            result = svc.verify_latest("database")
            print(json.dumps(result, ensure_ascii=False, indent=2) if result else "NO BACKUP TO VERIFY")
        elif args.sub == "list":
            print(json.dumps(svc.list_backups(kind=args.kind), ensure_ascii=False, indent=2))
        else:
            return 1
        return 0
    finally:
        db.close()


def _incidents(args) -> int:
    import json

    from .config import load_config
    from .ops.incidents import IncidentService
    from .storage.db import open_database

    cfg = load_config(ROOT)
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        svc = IncidentService(db)
        if args.sub == "list":
            for inc in svc.list(status=args.status, limit=args.n):
                print(f"{inc['incident_id'][:8]}  {inc['severity']:<8} {inc['status']:<12} "
                      f"{inc['type']:<20} {inc['description'][:50]}")
        elif args.sub == "show":
            print(json.dumps(svc.get(args.id) or {"error": "not found"}, ensure_ascii=False, indent=2))
        else:
            return 1
        return 0
    finally:
        db.close()


def _owner_alert_test(args) -> int:
    from .config import load_config
    from .ops.alerts import AlertDispatcher
    from .storage.db import open_database

    cfg = load_config(ROOT)
    status = transport_status_cli(cfg)
    if status in ("NOT_CONFIGURED", "log (fallback)"):
        print(f"NOT_CONFIGURED — alert channel '{cfg.scheduler.get('alert', {}).get('channel')}' "
              f"has no credentials in .env. Configure TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
              f"or SMTP_* to test a real delivery.")
        return 0
    db = open_database(cfg.database_path, ROOT / "amancore" / "storage" / "schema.sql")
    try:
        dispatcher = AlertDispatcher(db, config=cfg.scheduler.get("alert", {}))
        result = dispatcher.dispatch(
            severity="HIGH", category="owner_test", title="AmanCore owner alert test",
            summary="This is a test alert from aman-core owner-alert test.",
            action_required="confirm receipt",
        )
        print(f"DELIVERED via {result.get('transport')} (alert {result['alert_id'][:8]})")
        return 0
    finally:
        db.close()


def transport_status_cli(cfg) -> str:
    from .ops.alerts import transport_status

    return transport_status(cfg.scheduler.get("alert", {}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aman-core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    sub.add_parser("test")
    sub.add_parser("brain").add_argument("sub", choices=["validate", "versions"])
    sub.add_parser("config").add_argument("sub", choices=["check"])
    p_audit = sub.add_parser("audit")
    p_audit.add_argument("sub", choices=["recent"])
    p_audit.add_argument("-n", type=int, default=20)

    sub.add_parser("production-check")

    p_enable = sub.add_parser("production-enable")
    p_enable.add_argument("--confirm", required=True,
                          help='must be exactly: CONFIRM PRODUCTION ENABLE')
    p_enable.add_argument("--actor", default="owner")
    p_enable.add_argument("--dry-run", action="store_true")

    p_disable = sub.add_parser("production-disable")
    p_disable.add_argument("--actor", default="owner")
    p_disable.add_argument("--reason", default=None)

    p_webhook = sub.add_parser("webhook")
    p_webhook.add_argument("sub", choices=["serve"])
    p_webhook.add_argument("--host", default="127.0.0.1")
    p_webhook.add_argument("--port", type=int, default=8010)

    p_analytics = sub.add_parser("analytics")
    p_analytics.add_argument("sub", choices=["kpis", "funnel", "attribution", "report", "alerts"])
    p_analytics.add_argument("--period", choices=["daily", "weekly", "monthly"], default="daily")
    p_analytics.add_argument("--date", default=None)
    p_analytics.add_argument("--by", default="source_channel")

    p_support = sub.add_parser("support")
    p_support.add_argument("sub", choices=["list"])
    p_support.add_argument("--status", default=None)
    p_support.add_argument("-n", type=int, default=50)

    p_insights = sub.add_parser("insights")
    p_insights.add_argument("sub", choices=["list", "review", "recommendations", "report", "data-quality", "decide"])
    p_insights.add_argument("--status", default=None)
    p_insights.add_argument("--category", default=None)
    p_insights.add_argument("--period", choices=["daily", "weekly", "monthly"], default="daily")
    p_insights.add_argument("--date", default=None)
    p_insights.add_argument("--period-days", type=int, default=7)
    p_insights.add_argument("-n", type=int, default=50)
    p_insights.add_argument("id", nargs="?", default=None)
    p_insights.add_argument("decision", nargs="?", choices=["accept", "reject", "defer"], default=None)
    p_insights.add_argument("--reason", default="")
    p_insights.add_argument("--by", default="owner")

    sub.add_parser("status")

    p_jobs = sub.add_parser("jobs")
    p_jobs.add_argument("sub", choices=["status", "run", "tick", "loop"])
    p_jobs.add_argument("job", nargs="?", default=None)
    p_jobs.add_argument("--status", default=None)
    p_jobs.add_argument("-n", type=int, default=20)

    p_backup = sub.add_parser("backup")
    p_backup.add_argument("sub", choices=["create", "verify", "list"])
    p_backup.add_argument("--kind", default=None)

    p_incidents = sub.add_parser("incidents")
    p_incidents.add_argument("sub", choices=["list", "show"])
    p_incidents.add_argument("id", nargs="?", default=None)
    p_incidents.add_argument("--status", default=None)
    p_incidents.add_argument("-n", type=int, default=20)

    sub.add_parser("owner-alert-test")

    args = parser.parse_args(argv)
    if args.cmd == "health":
        return _health(args)
    if args.cmd == "test":
        return _test(args)
    if args.cmd == "brain":
        return _brain_validate(args) if args.sub == "validate" else _brain_versions(args)
    if args.cmd == "audit":
        return _audit_recent(args)
    if args.cmd == "config":
        return _config_check(args)
    if args.cmd == "production-check":
        return _production_check(args)
    if args.cmd == "production-enable":
        return _production_enable(args)
    if args.cmd == "production-disable":
        return _production_disable(args)
    if args.cmd == "webhook":
        if args.sub == "serve":
            from .channels.webhook_server import serve

            return serve(ROOT, host=args.host, port=args.port)
        return 1
    if args.cmd == "analytics":
        return _analytics(args)
    if args.cmd == "support":
        return _support(args)
    if args.cmd == "insights":
        return _insights(args)
    if args.cmd == "status":
        return _status(args)
    if args.cmd == "jobs":
        return _jobs(args)
    if args.cmd == "backup":
        return _backup(args)
    if args.cmd == "incidents":
        return _incidents(args)
    if args.cmd == "owner-alert-test":
        return _owner_alert_test(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
