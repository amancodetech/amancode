"""Job registry — maps job types to deterministic handlers.

Handlers read-only where possible; no automatic business changes.
Jobs with insufficient data are safe no-ops (research.daily stays off).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ..log import get_logger
from ..storage.db import Database

log = get_logger("ops.registry")

# job type -> schedule key in configs/scheduler.yaml
JOB_TYPES = (
    "research.daily", "followups.check", "outbox.drain",
    "analytics.daily", "analytics.weekly", "analytics.monthly",
    "insights.daily", "insights.weekly", "insights.monthly",
    "retention.cleanup", "database.backup", "backup.verify", "backup.restore_test",
    "health.check", "production.check", "content.autopilot",
    "executive.briefing", "consultation.reminders", "email.poll",
)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class JobRegistry:
    """Builds handlers bound to the live services. Deterministic."""

    def __init__(self, db, config, root):
        self.db = db
        self.config = config
        self.root = root

    def handlers(self) -> dict:
        cfg = self.config

        def _analytics(period: str):
            from ..analytics.service import AnalyticsService
            from ..insights.reports import InsightReports
            from ..insights.memory import InsightMemory

            analytics = AnalyticsService(self.db, config=cfg.analytics)
            reports = InsightReports(self.db, analytics, InsightMemory(self.db))
            if period == "daily":
                return reports.daily_brief(_today())
            if period == "weekly":
                return reports.weekly_review()
            return reports.monthly_review()

        def _insights(days: int):
            from ..analytics.service import AnalyticsService
            from ..insights.engine import InsightsEngine

            engine = InsightsEngine(self.db, analytics=AnalyticsService(self.db, config=cfg.analytics),
                                    config=cfg.insights)
            return engine.run(period_days=days)

        def _followups():
            """CC2: REAL follow-ups — policy-gated outbox messages with daily
            idempotency, then the lead's next_followup_at advances so we do
            not re-message daily.

            CHANNEL-NEUTRAL recipient selection is DETERMINISTIC: identities
            are tried in configured preference order; channels without an
            approved initiation template are skipped (never AI-chosen)."""
            from datetime import timedelta
            from ..ids import new_id, utcnow
            from ..channels.outbox import MessageOutbox

            # Compliance kit: consent + valve + per-channel template — safe defaults.
            from ..compliance.guard import ConsentGate, SendValve, TemplateLock

            comp = {}
            try:
                comp = dict(cfg.app.get("compliance") or {})
            except Exception:  # noqa: BLE001
                pass
            preference = list(comp.get("followup_channel_preference")
                              or ["whatsapp"])

            # resolve due leads once; recipients resolved per-identity below
            due = self.db.execute(
                "SELECT l.lead_id, l.name, l.language, "
                "       l.next_followup_at, l.opt_out, l.consent_at, c.mode "
                "FROM leads l LEFT JOIN conversations c ON c.lead_id = l.lead_id "
                "WHERE l.next_followup_at IS NOT NULL AND l.next_followup_at <= ? "
                "AND l.opt_out = 0 AND COALESCE(c.mode, 'AI_ACTIVE') = 'AI_ACTIVE'",
                (utcnow(),),
            ).fetchall()

            outbox = MessageOutbox(self.db)
            today = utcnow()[:10]
            enqueued, skipped_consent, skipped_channel, blocked_valve = [], 0, 0, 0
            for r in due:
                lead_row = dict(r)
                ok, why = ConsentGate.can_initiate(lead_row)
                if not ok:
                    skipped_consent += 1
                    continue
                sent_this_lead = False
                tpl_map = comp.get("approved_templates") or {}
                for channel in preference:
                    # deterministic template policy PER channel — a channel
                    # without an approved template NEVER receives initiations
                    ch_tpl = tpl_map.get(channel)
                    if ch_tpl is None and "followup" in tpl_map:
                        ch_tpl = tpl_map   # legacy flat shape (single-channel era)
                    tlock = TemplateLock(ch_tpl)
                    tmpl = tlock.resolve("followup")
                    if tmpl is None:
                        skipped_channel += 1
                        continue
                    ident = self.db.execute(
                        "SELECT external_user_id FROM platform_identities"
                        " WHERE lead_id=? AND channel=? LIMIT 1",
                        (r["lead_id"], channel)).fetchone()
                    ext = ident["external_user_id"] if ident else ""
                    if channel == "whatsapp" and not ext:
                        # legacy bridge for pre-identity leads
                        legacy = self.db.execute(
                            "SELECT contact_whatsapp c FROM leads WHERE lead_id=?",
                            (r["lead_id"],)).fetchone()
                        ext = (legacy["c"] or "") if legacy else ""
                    if not ext:
                        continue
                    adapter = None
                    try:
                        from .scheduler_adapter import build_adapters

                        adapters = build_adapters()
                        adapter = adapters.get(channel)
                    except Exception:  # noqa: BLE001 — factory optional in tests
                        adapter = None
                    recipient = (adapter.normalize_recipient(ext)
                                 if adapter is not None and
                                 callable(getattr(adapter, "normalize_recipient", None))
                                 else str(ext))
                    if not recipient:
                        continue
                    valve = SendValve(
                        self.db,
                        tiers=comp.get("warmup_tiers"),
                        tier_index=int(comp.get("warmup_tier", 0)),
                        auto_cap=int(comp.get("auto_send_cap", 50)),
                        channel=channel)
                    granted, _ = valve.reserve_initiations(1)
                    if not granted:
                        blocked_valve += 1
                        break   # cap reached — leave the rest for tomorrow
                    mid = outbox.enqueue(
                        channel=channel, recipient=recipient,
                        message_type="template",
                        payload={"name": tmpl["name"], "language":
                                 {"code": tmpl.get("language", "ar")}},
                        idempotency_key=f"followup:{channel}:{r['lead_id']}:{today}",
                        lead_id=r["lead_id"], correlation_id=new_id(),
                    )
                    self.db.execute(
                        "UPDATE message_outbox SET initiation='yes' WHERE message_id=?",
                        (mid,))
                    nxt = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
                    self.db.execute(
                        "UPDATE leads SET next_followup_at = ? WHERE lead_id = ?",
                        (nxt, r["lead_id"]))
                    enqueued.append(mid)
                    sent_this_lead = True
                    break   # ONE channel per follow-up by design — never multi-spam
                del sent_this_lead
            self.db.commit()
            return {"due_followups": len(due), "enqueued": len(enqueued),
                    "skipped_no_consent": skipped_consent,
                    "skipped_no_channel_policy": skipped_channel,
                    "blocked_by_valve": blocked_valve}

        def _retention():
            from ..ops.retention import RetentionService

            return RetentionService(self.db, config=cfg.retention).run()

        def _drain():
            """REAUD MEDIUM fix: retries/followups no longer wait for an
            inbound webhook — the scheduler drains every minute.

            CHANNEL-NEUTRAL: adapters come from the SAME composition factory as
            the runtime, and the REAL ChannelPolicyEngine gates sends (the old
            _AllowPolicy bypass that ignored warm-up ceilings is gone)."""
            from ..business_brain.store import BrainStore
            from ..channels.outbox import MessageOutbox, OutboxWorker
            from ..channels.policy import ChannelPolicyEngine
            from .scheduler_adapter import build_adapters

            adapters = build_adapters()
            brain = BrainStore(self.root / "amancore" / "business_brain")
            policy = ChannelPolicyEngine(brain, getattr(cfg, "channels", {}) or {})
            worker = OutboxWorker(MessageOutbox(self.db), adapters, policy)
            return {"drained": len(worker.drain(limit=25))}

        def _backup(payload=None):
            from ..ops.backup import BackupService

            return BackupService(self.db, self.root,
                                 database_path=self.root / cfg.database_path).create_backup(
                                     kind="all", payload=payload)

        def _backup_verify():
            from ..ops.backup import BackupService

            return BackupService(self.db, self.root,
                                 database_path=self.root / cfg.database_path).verify_latest()

        def _restore_test():
            """BAK-103: monthly proof that the latest backup actually restores.
            Restore to temp + integrity + row-count sanity. Never touches prod."""
            from ..ops.backup import BackupService

            svc = BackupService(self.db, self.root,
                                 database_path=self.root / cfg.database_path)
            latest = svc.latest_verified_database()
            if latest is None:
                raise RuntimeError("no verified database backup exists — restore test impossible")
            restored = svc.restore_to_temp(latest["backup_id"])
            rdb = Database(restored)
            try:
                tables = {r["name"] for r in rdb.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                counts = {t: rdb.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                          for t in ("leads", "conversations", "channel_messages",
                                    "message_outbox") if t in tables}
            finally:
                rdb.close()
            return {"status": "ok", "restored_from": latest["path"],
                    "row_counts": counts, "restored_at": _today()}

        def _health():
            from ..health import run_health_checks

            results = run_health_checks(self.root)
            return {"result": "PASS" if all(s == "PASS" for s, _ in results.values()) else "FAIL",
                    "checks": len(results)}

        def _production_check():
            from ..production.gate import ProductionGateService

            production = dict(cfg.production)
            production["_root"] = self.root
            report = ProductionGateService(production).check()
            return {"verdict": report["verdict"], "production_enabled": report["production_enabled"]}

        def _autopilot():
            from ..content.autopilot import ContentAutopilotEngine
            engine = ContentAutopilotEngine(db=self.db)
            return engine.run_daily_autopilot()

        def _executive_briefing():
            from ..analytics.briefing import ExecutiveBriefingService
            service = ExecutiveBriefingService(self.db, config=cfg.analytics if hasattr(cfg, "analytics") else None)
            text = service.format_telegram_briefing()
            # Send to Telegram owner if configured
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                import json
                import urllib.request
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                try:
                    urllib.request.urlopen(req, timeout=10)
                except Exception:
                    pass
            return {"status": "ok", "delivered": bool(token and chat_id)}

        def _consultation_reminders():
            from ..consultation.reminders import ConsultationReminderService
            service = ConsultationReminderService(self.db)
            return service.check_and_send_reminders()

        def _email_poll():
            """Inbound email leg: IMAP UNSEEN → coordinator → mark Seen."""
            import os as _os
            if not (_os.environ.get("EMAIL_IMAP_USER") or _os.environ.get("SMTP_USER")):
                return {"status": "skipped", "reason": "inbound email not configured"}
            if not (_os.environ.get("EMAIL_IMAP_PASSWORD") or _os.environ.get("SMTP_PASSWORD")):
                return {"status": "skipped", "reason": "inbound email not configured"}
            from ..channels.email_poll import mark_seen, poll_inbox_once
            from ..channels.webhook_server import build_runtime
            body = poll_inbox_once()
            if not body.get("emails"):
                return {"status": "ok", "received": 0}
            runtime = build_runtime(self.root)
            try:
                summary = runtime["coordinator"].handle_inbound("email", body)
            finally:
                try:
                    runtime["db"].close()
                except Exception:  # noqa: BLE001
                    pass
            if summary.get("processed"):
                mark_seen(body.get("uids") or [])
            return {"status": "ok", **{k: summary.get(k, 0)
                                       for k in ("received", "processed", "duplicates", "replies")}}

        return {
            "research.daily": lambda payload: {"note": "disabled (no live research router in mock mode)"},
            "followups.check": lambda p: _followups(),
            "analytics.daily": lambda p: _analytics("daily"),
            "analytics.weekly": lambda p: _analytics("weekly"),
            "analytics.monthly": lambda p: _analytics("monthly"),
            "insights.daily": lambda p: _insights(1),
            "insights.weekly": lambda p: _insights(7),
            "insights.monthly": lambda p: _insights(30),
            "retention.cleanup": lambda p: _retention(),
            "database.backup": lambda p: _backup(),
            "backup.verify": lambda p: _backup_verify(),
            "backup.restore_test": lambda p: _restore_test(),
            "outbox.drain": lambda p: _drain(),
            "health.check": lambda p: _health(),
            "production.check": lambda p: _production_check(),
            "content.autopilot": lambda p: _autopilot(),
            "executive.briefing": lambda p: _executive_briefing(),
            "consultation.reminders": lambda p: _consultation_reminders(),
            "email.poll": lambda p: _email_poll(),
        }
