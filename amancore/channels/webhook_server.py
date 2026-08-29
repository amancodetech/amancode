"""Webhook HTTP listener — exposes the WhatsApp webhook over local HTTP.

Transport only: all business logic stays in MessageCoordinator. Designed to
run on 127.0.0.1:8010 behind an HTTPS tunnel (e.g. Cloudflare). Uses the
standard library only (no new dependencies).

Endpoints:
    GET  /health              -> liveness probe
    GET  /webhook/whatsapp    -> Meta verification (hub.mode/verify_token/challenge)
    POST /webhook/whatsapp    -> signed event notifications -> coordinator

Security:
    - signature_required is honored: missing/invalid X-Hub-Signature-256 -> 403
    - malformed JSON -> 400
    - no secrets are ever logged or echoed
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..ids import utcnow
from ..log import get_logger

log = get_logger("channels.webhook_server")

MAX_BODY_BYTES = 1_000_000


_STATUS_RANK = {"processing": 1, "sent": 2, "delivered": 3, "read": 4}


def bridge_ingress_authorized(headers) -> bool:
    """Constant-time X-Bridge-Token check against BRIDGE_INGRESS_TOKEN.

    Fail-closed: an unset env var rejects everything (loud misconfiguration
    beats silent bypass) — same posture as signature_required."""
    import hmac as _hmac

    expected = os.environ.get("BRIDGE_INGRESS_TOKEN", "")
    supplied = (headers.get("X-Bridge-Token")
                or headers.get("x-bridge-token") or "")
    if not expected or not supplied:
        return False
    return _hmac.compare_digest(str(supplied).strip(), expected)


def make_status_recorder(db):
    """OUT-204 (C3): delivery receipts keep outbox + inbox rows truthful.

    Status moves FORWARD only (monotonic rank) so an out-of-order webhook
    can never downgrade a message (e.g. 'read' back to 'delivered', or a
    stale receipt resurrecting a dead row). Unknown provider ids are
    reported instead of silently dropped.
    """

    def _record_status(provider_message_id, status, recipient_id=None):
        if not provider_message_id:
            return {"updated": False, "reason": "empty id"}
        cur = db.execute(
            "SELECT id FROM channel_messages WHERE external_message_id = ? AND direction='out'",
            (provider_message_id,),
        ).fetchone()
        row = db.execute(
            "SELECT message_id, status, COALESCE(delivery_status, status) AS ds "
            "FROM message_outbox WHERE provider_message_id = ?",
            (provider_message_id,),
        ).fetchone()
        if row is None:
            log.warning("status.unknown_provider_id pmid=%s status=%s",
                        provider_message_id[:24], status)
            return {"updated": False, "reason": "unknown id"}

        current = row["ds"]
        if current in ("failed", "dead", "cancelled"):
            return {"updated": False, "reason": f"terminal {current}"}
        new_rank = _STATUS_RANK.get(status)
        if new_rank is not None and new_rank <= _STATUS_RANK.get(current, 0):
            return {"updated": False, "reason": "stale/out-of-order"}
        # C3 closure: provider receipts live in delivery_status — the LOCAL
        # send state machine stays inside its legal STATUSES set.
        db.execute(
            "UPDATE message_outbox SET delivery_status = ? WHERE provider_message_id = ?",
            (status, provider_message_id),
        )
        if cur is None:
            src = db.execute(
                "SELECT recipient, lead_id, payload FROM message_outbox WHERE provider_message_id = ?",
                (provider_message_id,),
            ).fetchone()
            if src is not None:
                db.execute(
                    "INSERT INTO channel_messages"
                    " (direction, channel, external_user_id, lead_id, external_message_id, body, status, created_at)"
                    " VALUES ('out', 'whatsapp', ?, ?, ?, ?, ?, ?)",
                    (src["recipient"], src["lead_id"], provider_message_id,
                     src["payload"] or "", status, utcnow()),
                )
                db.commit()
                return {"updated": True}
            # unknown id (e.g. AI auto-reply recorded via sync) — nothing to do
            return {"updated": False, "reason": "no inbox row"}
        db.execute(
            "UPDATE channel_messages SET status = ? WHERE id = ?", (status, cur["id"])
        )
        db.commit()
        return {"updated": True}

    return _record_status


def build_conversation_stack(root: Path, db, brain, crm, dispatcher,
                             audit, shared_router=None, owner_alert=None):
    """COM P0 wiring — the SINGLE composition point for conversation
    intelligence. Used by build_runtime AND by production-parity tests so
    the tested path and the live path cannot drift apart."""
    from ..agents.sales import SalesAgent
    from ..agents.support import SupportAgent
    from ..channels.handover import HandoverService
    from ..conversation import ConversationModel
    from ..conversation.pricing_flow import QuoteFlow
    from ..sales.conversation_memory import ConversationMemory
    from ..sales.discovery import DiscoveryEngine
    from ..pricing.snapshot import PricingSnapshotStore
    from ..sales.followup import FollowupEngine
    from ..sales.handoff import HandoffService
    from ..sales.qualification import QualificationEngine
    from ..services.owner_alert import send_owner_alert as _default_alert
    from ..skills.objection_handling import ObjectionHandlingSkill
    from ..support.cases import SupportCaseStore

    owner_alert = owner_alert or _default_alert
    memory = ConversationMemory(crm)

    # COM P0-2: hybrid fact extraction — live router on the sales agent.
    if shared_router is None:
        from ..routing.providers import build_providers
        from ..routing.router import ModelRouter, UsageTracker

        import yaml as _yaml

        with open(root / "configs" / "models.yaml") as _fh:
            _mcfg = _yaml.safe_load(_fh)
        shared_router = ModelRouter(_mcfg, build_providers(_mcfg),
                                    UsageTracker(db))

    sales = SalesAgent(
        brain, crm, memory, DiscoveryEngine(), QualificationEngine(),
        ObjectionHandlingSkill(brain), FollowupEngine(), HandoffService(dispatcher),
        router=shared_router,
        audit=audit, dispatcher=dispatcher,
    )

    # COM P0-4: support lane is LIVE in production.
    support = SupportAgent(
        brain, crm, SupportCaseStore(db), HandoverService(crm, dispatcher),
        owner_alert=owner_alert, dispatcher=dispatcher,
    )

    # COM P0-1: policy + modes + planner — single steering source.
    conversation = ConversationModel(root, brain)

    # COM P0-3: pricing tiers — T2 estimate + owner approval + T3 snapshot.
    quote_flow = QuoteFlow(db, crm, brain, PricingSnapshotStore(db),
                           dispatcher=dispatcher,
                           owner_alert=owner_alert, audit=audit)
    return {"memory": memory, "sales": sales, "support": support,
            "conversation": conversation, "quote_flow": quote_flow}


def build_runtime(root: Path):
    """Assemble the live coordinator stack from configs (mirrors test wiring)."""
    from ..agents.sales import SalesAgent
    from ..business_brain.store import BrainStore
    from ..channels.coordinator import MessageCoordinator
    from ..channels.handover import HandoverService
    from ..channels.language import LanguageDetector
    from ..channels.outbox import MessageOutbox, OutboxWorker
    from ..channels.policy import ChannelPolicyEngine
    from ..channels.response_filter import ExternalResponseFilter
    from ..config import load_config
    from ..crm.service import CRMService
    from ..pricing.proposal import ProposalStore
    from ..pricing.snapshot import PricingSnapshotStore
    from ..sales.conversation_memory import ConversationMemory
    from ..sales.discovery import DiscoveryEngine
    from ..sales.followup import FollowupEngine
    from ..sales.handoff import HandoffService
    from ..sales.qualification import QualificationEngine
    from ..services.audit import AuditService
    from ..services.events import EventDispatcher, IdempotencyStore
    from ..services.owner_alert import send_owner_alert
    from ..skills.localization import LocalizationSkill
    from ..skills.objection_handling import ObjectionHandlingSkill
    from ..storage.db import open_database

    cfg = load_config(root)
    db = open_database(cfg.database_path, root / "amancore" / "storage" / "schema.sql")

    # Bridge migration (owner spec §6): ONE resolution point for all channels.
    # Legacy mock/production semantics are preserved inside the resolver; only
    # an explicit `mode: bridge` block switches a channel to the local bridge.
    from ..channels.provider_resolver import (
        build_channel_adapter,
        resolve_channel_config,
    )

    prod_env = (cfg.production.get("environment") or {})

    brain = BrainStore(root / "amancore" / "business_brain")
    audit = AuditService(db)
    dispatcher = EventDispatcher()
    # PHASE-7: the events table is now real — every published event persists
    from ..services.events import wire_event_persistence

    wire_event_persistence(dispatcher, db)
    from ..channels.router import ChannelRouter

    adapters_by_channel: dict = {}
    for _name in ("whatsapp", "telegram", "facebook", "instagram"):
        _cfg = resolve_channel_config(_name, cfg.channels, prod_env)
        if _cfg is None:
            continue
        _adapter = build_channel_adapter(_name, _cfg)
        adapters_by_channel[_name] = _adapter
    adapter = adapters_by_channel["whatsapp"]
    router = ChannelRouter(dict(adapters_by_channel))
    tg_adapter = adapters_by_channel.get("telegram")
    meta_adapters: dict = {k: v for k, v in adapters_by_channel.items()
                           if k in ("facebook", "instagram")}

    outbox = MessageOutbox(db)
    policy = ChannelPolicyEngine(brain, getattr(cfg, "channels", {}) or {})
    try:
        outbox_cfg = dict(cfg.channels.get("outbox") or {})
    except Exception:  # noqa: BLE001 — config drift must never kill startup
        outbox_cfg = {}
    from ..compliance.guard import SendValve

    try:
        _comp = dict(cfg.app.get("compliance") or {})
    except Exception:  # noqa: BLE001
        _comp = {}
    valve = SendValve(db, tiers=_comp.get("warmup_tiers"),
                      tier_index=int(_comp.get("warmup_tier", 0)),
                      auto_cap=int(_comp.get("auto_send_cap", 50)))
    worker = OutboxWorker(
        outbox, router, policy, audit=audit, dispatcher=dispatcher,
        claim_mode=str(outbox_cfg.get("claim_mode", "legacy")),
        stale_after_seconds=int(outbox_cfg.get("stale_after_seconds", 300)),
        owner_alert=send_owner_alert,
        send_valve=valve,
    )
    crm = CRMService(db)
    # COM P0: ONE composition point for conversation intelligence — the
    # exact stack the production-parity tests exercise.
    stack = build_conversation_stack(root, db, brain, crm, dispatcher, audit)
    memory = stack["memory"]
    sales = stack["sales"]
    support = stack["support"]
    conversation = stack["conversation"]
    quote_flow = stack["quote_flow"]

    from ..ops.cost_governor import CostGovernor

    cost_cfg = {}
    try:
        cost_cfg = dict(cfg.app.get("cost") or {})
    except Exception:  # noqa: BLE001 — governor must never block startup
        cost_cfg = {}
    governor = CostGovernor(cost_cfg)

    coordinator = MessageCoordinator(
        # full channel registry (router and coordinator MUST agree) — the
        # live-verification 500 proved a router-only registration is not enough
        ({"whatsapp": adapter} | ({"telegram": tg_adapter} if tg_adapter else {})
         | meta_adapters),
        outbox, worker, sales, crm, memory,
        HandoverService(crm, dispatcher), ExternalResponseFilter(), policy,
        IdempotencyStore(db), LanguageDetector(), LocalizationSkill(),
        PricingSnapshotStore(db), ProposalStore(db),
        owner_alert=send_owner_alert,
        audit=audit, dispatcher=dispatcher,
        cost_governor=governor,
        conversation=conversation,
        quote_flow=quote_flow,
        support_agent=support,
    )
    inbox = build_inbox_runtime(db, coordinator)

    if inbox is not None:
        def _record_inbound(direction, channel, external_user_id, lead_id,
                            external_message_id=None, body="",
                            quoted_external_message_id=None, **_):
            from ..ids import utcnow

            db.execute(
                "INSERT INTO channel_messages"
                " (direction, channel, external_user_id, lead_id, external_message_id,"
                "  body, status, created_at, quoted_external_message_id)"
                " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)",
                (direction, channel, external_user_id, lead_id, external_message_id,
                 body, utcnow(), quoted_external_message_id or None),
            )
            db.commit()

        coordinator.message_recorder = _record_inbound

        def _record_reaction(payload):
            """Customer reaction on our message: set/clear emoji chip in place."""
            wmid = payload.get("target_external_message_id") or payload.get("message_id")
            if not wmid:
                return
            emoji = payload.get("emoji") or None  # empty emoji == reaction removed
            cur = db.execute(
                "UPDATE channel_messages SET reaction=? WHERE external_message_id=?",
                (emoji, wmid),
            )
            if cur.rowcount == 0 and emoji:
                # reaction on a message we have no row for — record as standalone note
                db.execute(
                    "INSERT INTO channel_messages"
                    " (direction, channel, external_user_id, lead_id, external_message_id,"
                    "  body, status, created_at, reaction)"
                    " VALUES ('in', COALESCE(?, 'whatsapp'), ?, NULL, ?, '', '', datetime('now'), ?)",
                    (payload.get("channel"), payload.get("external_user_id") or "", wmid, emoji),
                )
            db.commit()

        coordinator.status_recorder = make_status_recorder(db)
        coordinator.reaction_recorder = _record_reaction
        runtime_inbox_sync = lambda: sync_channel_messages(db)  # noqa: E731
    else:
        runtime_inbox_sync = lambda: None  # noqa: E731

    if inbox is not None:
        inbox["adapter"] = adapter
        inbox["router"] = router
        inbox["valve"] = valve
    try:
        channels_view = dict(cfg.channels or {})
    except Exception:  # noqa: BLE001
        channels_view = {}
    runtime = {"db": db, "adapter": adapter, "router": router,
               "coordinator": coordinator,
               "inbox": inbox, "sync": runtime_inbox_sync,
               "config_channels": channels_view,
               "cost_governor": governor,
               "quote_flow": quote_flow}
    return runtime


def notify_owner_console(runtime, text: str) -> None:
    """Push a short report to the owner's Telegram chat (fire-and-forget)."""
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return
        payload = json.dumps({"chat_id": chat, "text": text[:3500],
                              "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:  # noqa: BLE001 — reporting must never break serving
        log.error("owner console notify failed: %s", exc)


def sync_channel_messages(db) -> None:
    """Reconcile outbound rows with the outbox so ticks/statuses stay truthful.

    - manual sends (channel_messages.outbox_message_id set): copy status +
      provider_message_id from their outbox row
    - AI/auto replies (outbox-only): adopt into channel_messages once
    """
    db.execute(
        """
        UPDATE channel_messages SET
          status = COALESCE((SELECT o.status FROM message_outbox o
                             WHERE o.message_id = channel_messages.outbox_message_id), status),
          external_message_id = COALESCE(
              (SELECT o.provider_message_id FROM message_outbox o
               WHERE o.message_id = channel_messages.outbox_message_id), external_message_id)
        WHERE direction='out' AND outbox_message_id IS NOT NULL
        """
    )
    db.execute(
        """
        INSERT INTO channel_messages
          (direction, channel, external_user_id, lead_id, external_message_id,
           body, status, created_at, outbox_message_id)
        SELECT 'out', o.channel, o.recipient, o.lead_id, o.provider_message_id,
               COALESCE(o.payload, ''), o.status, o.created_at, o.message_id
          FROM message_outbox o
         WHERE o.message_type='text'
           AND o.provider_message_id IS NOT NULL
           AND o.created_at >= datetime('now', '-7 days')
           AND NOT EXISTS (
               SELECT 1 FROM channel_messages c WHERE c.outbox_message_id = o.message_id)
         ON CONFLICT(channel, external_message_id) WHERE external_message_id IS NOT NULL DO NOTHING
        """
    )
    db.commit()


def build_inbox_runtime(db, coordinator):
    """Assemble the private owner inbox (auth + message store + send path)."""
    from .handover import HandoverService
    from .inbox import InboxConfig

    cfg = InboxConfig()
    if not cfg.configured:
        return None  # inbox disabled unless fully configured in env
    from ..crm.service import CRMService

    return {
        "config": cfg,
        "db": db,
        "crm": CRMService(db),
        "handover": HandoverService(CRMService(db)),
        "outbox": coordinator.outbox,
        "worker": coordinator.worker,
    }



def resolve_client_key(headers, peer_addr: str | None, trust_proxy: bool) -> str:
    """S2: proxy IP headers are trusted ONLY when the deployment flag says we
    actually sit behind that proxy — otherwise a client can spoof
    CF-Connecting-IP and rotate free brute-force buckets."""
    if trust_proxy:
        cf_ip = headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
    return peer_addr or "?"

_PRIVACY_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AmanCode — سياسة الخصوصية / Privacy Policy</title>
<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:820px;margin:auto;padding:24px;line-height:1.7;color:#1c2333}h1{color:#0b63c5}.en{direction:ltr;text-align:left;border-top:2px solid #e3e8f0;margin-top:28px;padding-top:16px}</style></head><body>
<h1>سياسة الخصوصية — AmanCode</h1>
<p>آخر تحديث / Last updated: 2026-08-27</p>

<h2>ما نجمعه</h2>
<p>يدير مساعد «AmanCode» محادثات المبيعات عبر واتساب وماسنجر وإنستغرام وتليجرام. عند تواصلك معنا نُخزّن:</p>
<ul>
<li>مُعرِّف الحساب الذي تستخدمه للتواصل (رقم الواتساب، مُعرّف مسنجر/إنستغرام، معرّف تيليجرام).</li>
<li>محتوى الرسائل التي ترسلها لنا والردود المُولّدة لمساعدتك.</li>
<li>توقيتات المحادثة وبعض تفاصيل الطلب مثل نوع المشروع لتجهيز عرض السعر.</li>
</ul>

<h2>كيف نستخدم البيانات</h2>
<p>لاستخدامها حصراً في: تجهيز عروض الأسعار، متابعة طلباتك، دعم ما بعد التسليم، وتحسين جودة الردود. لا نبيع بياناتك ولا نشاركها مع أي طرف ثالث لأغراض إعلانية.</p>

<h2>مكان التخزين والاحتفاظ</h2>
<p>تُحفظ البيانات على خوادمنا الخاصة مشفّرة أثناء النقل. نحتفظ بمحتوى المحادثة خلال فترة نشاط التعامل، وبعدها يُحذف تلقائياً حسب جدول الاستبقاء الدوري.</p>

<h2>حقوقك</h2>
<p>يمكنك في أي وقت طلب نسخة من بياناتك أو تصحيحها أو <strong>حذفها نهائياً</strong> عبر مراسلتنا على نفس القناة بكلمة «حذف بياناتي»، أو مراسلة البريد أدناه.</p>
<p>البريد: <a href="mailto:amancode.tech@gmail.com">amancode.tech@gmail.com</a></p>

<div class="en">
<h2>Privacy Policy — AmanCode</h2>
<p><strong>Data we collect:</strong> your channel account identifier (WhatsApp number / Messenger or Instagram ID / Telegram ID), the messages you send us, our generated replies, and basic request details such as project type for quotations.</p>
<p><strong>Use:</strong> solely to prepare quotes, follow up on your requests, provide support, and improve response quality. We never sell your data or share it with third parties for advertising.</p>
<p><strong>Storage &amp; retention:</strong> data is stored on our own servers, encrypted in transit, and auto-deleted per retention schedule once the business relationship ends.</p>
<p><strong>Your rights:</strong> request access, correction, or permanent deletion any time via the same channel or by email below.</p>
<p>Contact: <a href="mailto:amancode.tech@gmail.com">amancode.tech@gmail.com</a></p>
</div></body></html>"""

_DATA_DELETION_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AmanCode — حذف البيانات / Data Deletion</title>
<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:820px;margin:auto;padding:24px;line-height:1.7;color:#1c2333}h1{color:#0b63c5}.en{direction:ltr;text-align:left;border-top:2px solid #e3e8f0;margin-top:28px;padding-top:16px}</style></head><body>
<h1>حذف بياناتك — AmanCode</h1>

<h2>طريقة الحذف</h2>
<ol>
<li>أرسل كلمة <strong>«حذف بياناتي»</strong> إلى صفحتنا/حسابنا على أي قناة تواصلت منها (واتساب، ماسنجر، إنستغرام، تليجرام)؛ أو</li>
<li>راسلنا بريداً على <a href="mailto:amancode.tech@gmail.com">amancode.tech@gmail.com</a> من حسابك المرتبط بالتواصل السابق.</li>
</ol>
<p>سنحذف نهائياً خلال 72 ساعة: مُعرِّف حسابك، كل رسائلك المخزنة، سجل المحادثة المرتبط به، وأي معطيات اشتقناها منه، ونؤكد لك الحذف عبر القناة نفسها.</p>

<div class="en">
<h2>Data Deletion Instructions</h2>
<ol><li>Message our page/account on any channel you previously used (WhatsApp, Messenger, Instagram, Telegram) with the text “delete my data” in Arabic or English; or</li><li>Email amancode.tech@gmail.com from your linked account.</li></ol>
<p>All stored identifiers, messages, conversation history and derived records tied to your account are permanently erased within 72 hours, and we confirm back on the same channel.</p>
</div></body></html>"""

class WebhookRequestHandler(BaseHTTPRequestHandler):
    server_version = "AmanCoreWebhook/1.0"

    # the runtime dict is attached to the HTTPServer instance
    @property
    def runtime(self) -> dict:
        return self.server.runtime

    @property
    def inbox(self):
        return self.runtime.get("inbox")

    def _webhook_channel(self, path: str) -> str | None:
        """Path registry: /webhook/<channel> → channel with a registered adapter."""
        router = self.runtime.get("router")
        if router is None:
            # minimal runtimes (tests/tools) may only carry a coordinator
            coord = self.runtime.get("coordinator")
            adapters = getattr(coord, "adapters", None) or {}
            if path.startswith("/webhook/"):
                candidate = path[len("/webhook/"):]
                return candidate if candidate in adapters else None
            return None
        if not path.startswith("/webhook/"):
            return None
        candidate = path[len("/webhook/"):]
        return candidate if router.has(candidate) else None

    def _inbox_route(self, path: str) -> tuple[object | None, str]:
        """Match /{slug}/{action} -> (inbox_runtime, action)."""
        inbox = self.inbox
        if inbox is None:
            return None, ""
        slug = inbox["config"].slug
        prefix = f"/{slug}/"
        if path.startswith(prefix):
            return inbox, path[len(prefix):]
        if path == f"/{slug}":
            return inbox, "login"
        return None, ""

    def log_message(self, fmt, *args):  # noqa: A003 — redacted, no bodies/secrets
        import re as _re

        line = fmt % args
        # never log tokens or signatures
        line = _re.sub(r"(hub\.verify_token=)[^&\s]+", r"\1<redacted>", line)
        line = _re.sub(r"(access_token=)[^&\s]+", r"\1<redacted>", line)
        entry = f"{self.address_string()} - {line}"
        print(entry, flush=True)
        log.info(entry)

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, page: str, extra_headers: dict | None = None) -> None:
        from .inbox import security_headers

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page.encode("utf-8"))))
        for k, v in security_headers().items():
            self.send_header(k, v)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def do_GET(self):  # noqa: N802 — stdlib naming
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, b"ok")
            return
        if parsed.path == "/privacy":
            return self._send_html(200, _PRIVACY_PAGE)
        if parsed.path == "/data-deletion":
            return self._send_html(200, _DATA_DELETION_PAGE)
        channel = self._webhook_channel(parsed.path)
        if channel is not None:
            qs = parse_qs(parsed.query)
            mode = (qs.get("hub.mode") or [""])[0]
            token = (qs.get("hub.verify_token") or [""])[0]
            challenge = (qs.get("hub.challenge") or [""])[0]
            result = self.runtime["coordinator"]._adapter_for(channel).verify_webhook(mode, token, challenge)
            if result.get("verified"):
                self._send(200, result["challenge"].encode("utf-8"))
            else:
                self._send(403, b"verification failed")
            return
        inbox, action = self._inbox_route(parsed.path)
        if inbox is not None and not action.startswith("api"):
            return self._inbox_get(inbox, action, parsed.query)
        if inbox is not None and action.startswith("api/"):
            if not self._inbox_session_ok(inbox):
                self._send(403, b"forbidden", "application/json")
                return
            return self._inbox_api_get(inbox, action[len("api/"):], parse_qs(parsed.query))
        self._send(404, b"not found")

    def do_POST(self):  # noqa: N802 — stdlib naming
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path == "/bridge/inbound":
            return self._bridge_inbound()
        inbox, action = self._inbox_route(parsed.path)
        if inbox is not None:
            return self._inbox_post(inbox, action)
        channel = self._webhook_channel(parsed.path)
        if channel is None:
            self._send(404, b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY_BYTES:
            self._send(400, b"bad content length")
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, b"malformed json")
            return
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            summary = self.runtime["coordinator"].handle_inbound(
                channel, body, headers, raw_body=raw
            )
        except Exception as exc:  # noqa: BLE001 — respond, never leak internals
            log.error("webhook processing failed: %s", exc)
            self._send(500, b"internal error")
            return
        sync = self.runtime.get("sync")
        if sync:
            sync()
        if summary.get("replies"):
            try:
                # channel-neutral sender lookup (was Meta-payload + legacy wa_id
                # SQL — silently dead since the canonical migration)
                last_in = self.runtime["db"].execute(
                    "SELECT channel, external_user_id FROM channel_messages"
                    " WHERE direction='in' ORDER BY id DESC LIMIT 1").fetchone()
                frm_channel = (last_in["channel"] if last_in else "") or "unknown"
                frm = (last_in["external_user_id"] if last_in else "") or ""
                if frm:
                    row = self.runtime["db"].execute(
                        "SELECT body FROM channel_messages WHERE direction='out'"
                        " AND external_user_id=? AND channel=? ORDER BY id DESC LIMIT 1",
                        (frm, frm_channel)).fetchone()
                    last = (row["body"][:300] if row else "")
                    notify_owner_console(
                        self.runtime,
                        "🤖 ردّيتُ على {ch}:{frm}:\n«{last}»".format(
                            ch=frm_channel, frm=frm, last=last))
                    in_row = self.runtime["db"].execute(
                        "SELECT body FROM channel_messages"
                        " WHERE direction='in' AND external_user_id=? AND channel=?"
                        " AND body != '' ORDER BY id DESC LIMIT 1",
                        (frm, frm_channel)).fetchone()
                    if in_row:
                        import threading as _th
                        from ..ops.learning import record_learning

                        gov = self.runtime.get("cost_governor")

                        def _governed_learn(_frm=frm, _in=in_row["body"], _out=last):
                            if gov is not None and not gov.allow(_frm)[0]:
                                return
                            record_learning(_frm, _in, _out)
                            if gov is not None:
                                gov.record(_frm, len(_in) + len(_out), 200)

                        _th.Thread(target=_governed_learn, daemon=True).start()
            except Exception:  # noqa: BLE001
                pass
        if summary.get("status") == "rejected":
            self._send(403, json.dumps(summary).encode("utf-8"), "application/json")
            return
        self._send(200, json.dumps(summary).encode("utf-8"), "application/json")

    # ── local bridge ingress (owner spec §12) ───────────────────────────

    def _bridge_inbound(self) -> None:
        """POST /bridge/inbound — the meta-bridge pushes normalized envelopes.

        Auth: X-Bridge-Token (constant-time vs BRIDGE_INGRESS_TOKEN env).
        ACK contract (NEVER an ambiguous 200):
          200 {"accepted":true,"event_id":...,"duplicate":false|true}
          400 {"accepted":false,"retryable":false,"error_code":"INVALID_ENVELOPE"}
          403 {"accepted":false,"retryable":false,"error_code":"UNAUTHORIZED"}
          500 {"accepted":false,"retryable":true,"error_code":"TEMPORARY_UNAVAILABLE"}
        """
        _ack = self._send_json
        if not bridge_ingress_authorized(self.headers):
            return _ack(403, {"accepted": False, "retryable": False,
                              "error_code": "UNAUTHORIZED"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY_BYTES:
            return _ack(400, {"accepted": False, "retryable": False,
                              "error_code": "BAD_CONTENT_LENGTH"})
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _ack(400, {"accepted": False, "retryable": False,
                              "error_code": "MALFORMED_JSON"})
        if isinstance(body, list):
            accepted, responses = 0, []
            for item in body:
                accepted += self._bridge_envelope_ack(item, responses)
            sync = self.runtime.get("sync")
            if sync and accepted:
                sync()
            return _ack(200, {"accepted": True, "batch": responses})
        responses: list = []
        ok = self._bridge_envelope_ack(body, responses)
        if not ok:
            code = (responses[-1] or {}).get("error_code")
            status = 400 if code in ("INVALID_ENVELOPE", "UNKNOWN_CHANNEL",
                                     "MALFORMED_JSON") else 500
            return _ack(status, responses[-1])
        sync = self.runtime.get("sync")
        if sync:
            sync()
        return _ack(200, responses[-1])

    def _bridge_envelope_ack(self, envelope: dict, responses: list) -> bool:
        """Normalize one envelope + run it through the shared intake.
        Appends the ACK dict to `responses`; returns True when accepted."""
        from .bridge_envelope import EnvelopeError, normalize_envelope

        try:
            event = normalize_envelope(envelope)
        except EnvelopeError as exc:
            responses.append({"accepted": False, "retryable": False,
                              "error_code": exc.error_code,
                              "detail": str(exc)[:160]})
            return False
        try:
            ack = self.runtime["coordinator"].handle_bridge_event(event)
        except Exception as exc:  # noqa: BLE001 — mapped to retryable ACK
            log.error("bridge.inbound processing failed: %s", exc)
            responses.append({"accepted": False, "retryable": True,
                              "error_code": "TEMPORARY_UNAVAILABLE"})
            return False
        responses.append(ack)
        return bool(ack.get("accepted"))

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json")

    # ── private owner inbox ─────────────────────────────────────────────

    def _inbox_session_ok(self, inbox) -> bool:
        from .inbox import extract_session_cookie, verify_session_token

        token = extract_session_cookie(self.headers.get("Cookie"))
        return verify_session_token(inbox["config"].secret, token)

    def _client_key(self) -> str:
        inbox_cfg = self.runtime.get("inbox", {}).get("config") if self.runtime else None
        trust_proxy = getattr(inbox_cfg, "trust_proxy_ip", False)
        return resolve_client_key(self.headers, self.client_address[0], trust_proxy)

    def _inbox_get(self, inbox, action: str, query: str) -> None:
        from .inbox import render_inbox_page, render_login_page

        cfg = inbox["config"]
        if action in ("login", ""):
            already = self._inbox_session_ok(inbox)
            if already:
                return self._redirect(cfg.app_path)
            return self._send_html(200, render_login_page(cfg.login_path))
        if action == "app":
            if not self._inbox_session_ok(inbox):
                return self._redirect(cfg.login_path)
            base = f"/{cfg.slug}"
            return self._send_html(200, render_inbox_page(base, f"{base}/logout"))
        self._send(404, b"not found")

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_form(self) -> dict:
        from urllib.parse import parse_qs

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 10_000:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _read_json(self, max_bytes: int = 1_000_000) -> dict:
        """S4: tight default cap for JSON APIs; only the media-upload action
        opts into the larger bound (base64 ≈ 30MB binary needs ~40MB text)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= max_bytes:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _inbox_post(self, inbox, action: str) -> None:
        from .inbox import (
            SESSION_COOKIE,
            LoginRateLimiter,
            make_session_token,
            render_login_page,
            security_headers,
            verify_password,
        )

        cfg = inbox["config"]
        limiter: LoginRateLimiter = self.runtime.setdefault(
            "_login_limiter", LoginRateLimiter()
        )
        client = self._client_key()

        if action == "logout":
            # S4: unauthenticated force-logout was a one-click DoS on owners
            if not self._inbox_session_ok(inbox):
                return self._send(403, b"forbidden")
            secure_attr = "; Secure" if getattr(cfg, "secure_cookie", False) else ""
            expired = (f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; "
                       f"SameSite=Strict{secure_attr}")
            return self._send_html(303, "", {"Set-Cookie": expired, "Location": cfg.login_path})

        if action == "login":
            form = self._read_form()
            password = form.get("password", "")
            if limiter.is_locked(client):
                return self._send_html(429, render_login_page(cfg.login_path, "محاولات كثيرة — حاول بعد 10 دقائق"))
            if not password or not verify_password(password, cfg.password_hash):
                limiter.record_failure(client)
                import time as _t

                _t.sleep(1.0)  # brute-force damping
                return self._send_html(200, render_login_page(cfg.login_path, "كلمة مرور غير صحيحة"))
            limiter.reset(client)
            token = make_session_token(cfg.secret)
            secure_attr = "; Secure" if getattr(cfg, "secure_cookie", False) else ""
            cookie = (
                f"{SESSION_COOKIE}={token}; Path=/; Max-Age={12 * 60 * 60}; "
                f"HttpOnly; SameSite=Strict{secure_attr}"
            )
            return self._send_html(
                303, "", {"Set-Cookie": cookie, "Location": cfg.app_path}
            )

        if not self._inbox_session_ok(inbox):
            return self._send(403, b"forbidden")

        if action == "api/react":
            data = self._read_json()
            wa_id = str(data.get("wa_id") or "").strip()
            wamid = str(data.get("message_id") or "").strip()
            emoji = str(data.get("emoji") or "").strip()
            if not wa_id or not wamid:
                return self._send(400, b"bad request")
            try:
                self.runtime["adapter"].react(wa_id, wamid, emoji)
                return self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                log.error("reaction failed: %s", exc)
                return self._send(502, json.dumps({"ok": False, "error": str(exc)[:150]}).encode(), "application/json")

        if action == "api/read":
            data = self._read_json()
            wamids = data.get("message_ids") or []
            if not isinstance(wamids, list):
                return self._send(400, b"bad request")
            adapter = self.runtime["adapter"]
            ok_count = 0
            for wmid in wamids[:50]:
                if not isinstance(wmid, str) or not wmid.strip():
                    continue
                try:
                    adapter.mark_read(wmid)
                    ok_count += 1
                except Exception:  # noqa: BLE001 — best effort receipts
                    pass
            return self._send(200, json.dumps({"ok": True, "marked": ok_count}).encode(), "application/json")

        if action == "api/hide":
            data = self._read_json()
            msg_pk = data.get("id")
            if not isinstance(msg_pk, int):
                return self._send(400, b"bad request")
            inbox["db"].execute(
                "UPDATE channel_messages SET hidden = 1 WHERE id = ? AND direction='out'", (msg_pk,)
            )
            inbox["db"].commit()
            return self._send(200, json.dumps({"ok": True}).encode(), "application/json")

        if action == "api/send":
            data = self._read_json()
            wa_id = str(data.get("wa_id") or "").strip()
            text = str(data.get("text") or "").strip()
            media = data.get("media") or None
            if media is not None and (
                not isinstance(media, dict)
                or media.get("kind") not in ("image", "audio", "video", "document")
                or not isinstance(media.get("data_base64"), str)
                or len(media["data_base64"]) > 40_000_000  # ~30MB binary
            ):
                return self._send(400, json.dumps({"ok": False, "error": "bad media"}).encode(), "application/json")
            if (not wa_id) or (not text and not media):
                return self._send(400, b"bad request")
            max_len = int(((self.runtime.get("config_channels") or {})
                           .get("whatsapp", {}) or {}).get("max_text_length", 4096))
            if len(text) > max_len:
                return self._send(400, json.dumps({"ok": False, "error": "text too long"}).encode(), "application/json")
            reply_to = str(data.get("reply_to") or "").strip() or None
            result = inbox_send_message(inbox, wa_id, text, media=media, reply_to=reply_to)
            status = 200 if result.get("ok") else 502
            return self._send(status, json.dumps(result).encode("utf-8"), "application/json")

        self._send(404, b"not found")

    def _inbox_api_get(self, inbox, resource: str, qs: dict) -> None:
        if resource == "leads":
            rows = inbox["db"].execute(
                """
                SELECT l.contact_whatsapp AS wa_id,
                       COALESCE(l.name, '') AS name,
                       COALESCE(c.mode, 'AI_ACTIVE') AS mode,
                       MAX(m.created_at) AS last_at,
                       (SELECT COUNT(*) FROM channel_messages u
                         WHERE u.external_user_id = l.contact_whatsapp AND u.direction='in'
                           AND u.status IS NOT 'read' AND u.hidden = 0
                           AND u.external_message_id IS NOT NULL) AS unread
                  FROM leads l
             LEFT JOIN conversations c ON c.lead_id = l.lead_id
             LEFT JOIN channel_messages m ON m.external_user_id = l.contact_whatsapp
              GROUP BY l.contact_whatsapp
              ORDER BY last_at DESC NULLS LAST
                 LIMIT 200
                """
            ).fetchall()
            payload = [dict(r) for r in rows]
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
        if resource == "messages":
            sync_channel_messages(inbox["db"])
            wa_id = (qs.get("wa_id") or [""])[0]
            before_id = (qs.get("before_id") or [""])[0]
            base_sql = """
                SELECT m.id, m.direction, m.body, m.status, m.created_at,
                       m.media_kind, m.media_ref, m.external_message_id, m.reaction,
                       (SELECT substr(q.body, 1, 80) FROM channel_messages q
                         WHERE q.external_message_id = m.quoted_external_message_id) AS quoted
                  FROM channel_messages m WHERE m.external_user_id = ? AND m.hidden = 0
                """
            if before_id:  # U3: older-page fetch (client paginates past 500)
                rows = inbox["db"].execute(
                    base_sql + " AND m.id < ?"
                    " ORDER BY m.created_at DESC, m.id DESC LIMIT 200",
                    (wa_id, int(before_id)),
                ).fetchall()
                rows.reverse()
            else:
                # U3 fix: the DEFAULT page must be the NEWEST 500 (rendered
                # ascending) — the old ASC-LIMIT showed only ancient history
                # once a chat passed 500 messages.
                rows = inbox["db"].execute(
                    base_sql + " ORDER BY m.created_at DESC, m.id DESC LIMIT 500",
                    (wa_id,),
                ).fetchall()
                rows.reverse()
            payload = []
            for r in rows:
                d = dict(r)
                body = d.pop("body") or ""
                if d.get("media_kind"):
                    d["media"] = {"kind": d.pop("media_kind"), "ref": d.pop("media_ref")}
                    d["caption"] = body
                else:
                    d.pop("media_kind", None); d.pop("media_ref", None)
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and parsed.get("kind"):
                            d["media"] = {"kind": parsed["kind"], "ref": parsed.get("ref"),
                                          "filename": parsed.get("filename")}
                            d["caption"] = parsed.get("caption", "")
                        else:
                            d["caption"] = body
                    except (ValueError, TypeError):
                        d["caption"] = body
                payload.append(d)
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
        if resource == "media":
            ref = (qs.get("ref") or [""])[0]
            if not ref or not ref.isalnum():
                return self._send(400, b"bad ref")
            adapter = self.runtime["adapter"]
            provider = getattr(adapter, "provider", None)
            dl = getattr(provider, "download_media", None)
            if dl is None:
                return self._send(501, b"media download unavailable in mock mode")
            try:
                data, mime = dl(ref)
            except Exception as exc:  # noqa: BLE001
                log.error("media download failed: %s", exc)
                return self._send(502, b"download failed")
            return self._send(200, data, mime)
        self._send(404, b"not found")


def inbox_send_message(inbox, wa_id: str, text: str, media: dict | None = None,
                       reply_to: str | None = None, *,
                       initiation: bool = False) -> dict:
    """Owner manual reply (initiation=False) or business-initiated outreach
    (initiation=True — REAUD HIGH: gated by ConsentGate + 24h window +
    SendValve reservation, and tagged initiation='yes' for cap accounting)."""
    if initiation:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        from ..compliance.guard import ConsentGate, SendValve

        db0 = inbox["db"]
        lrow = db0.execute(
            "SELECT opt_out, consent_at FROM leads l"
            " JOIN platform_identities i ON i.lead_id = l.lead_id"
            " WHERE i.channel='whatsapp' AND i.external_user_id=?"
            " ORDER BY l.created_at DESC LIMIT 1", (wa_id,)).fetchone()
        if lrow is None:
            lrow = db0.execute(
                "SELECT opt_out, consent_at FROM leads WHERE contact_whatsapp=?"
                " ORDER BY created_at DESC LIMIT 1", (wa_id,)).fetchone()
        lead_dict = dict(lrow) if lrow else {}
        ok, why = ConsentGate.can_initiate(lead_dict)
        if not ok:
            return {"ok": False, "error": f"consent gate: {why}"}
        last_in = db0.execute(
            "SELECT MAX(created_at) m FROM channel_messages WHERE external_user_id=?"
            " AND direction='in'", (wa_id,)).fetchone()["m"]
        window = None
        if last_in:
            window = (_dt.now(_tz.utc)
                      - _dt.fromisoformat(last_in)).total_seconds() < 86400
        has_tpl = bool((inbox.get("config") and getattr(
            inbox["config"], "approved_templates", None)))
        if not window and not has_tpl:
            return {"ok": False, "error":
                    "outside 24h customer window — use an approved template "
                    "(compliance kit blocks free-text initiation)"}
        # REAUD fix: use the SHARED runtime valve so in-process reservations
        # count against the same cap the worker enforces (was a fresh instance).
        valve = inbox.get("valve") or SendValve(db0)
        granted, why = valve.reserve_initiations(1)
        if not granted:
            return {"ok": False, "error": f"send valve: {why}"}
    import base64
    import tempfile
    import uuid

    from .handover import HandoverService
    from ..ids import utcnow
    from ..services.audit import AuditService

    crm = inbox["crm"]
    lead = crm.find_lead_by_whatsapp(wa_id)
    if lead is None:
        lead_id = crm.create_lead(contact_whatsapp=wa_id, source_channel="whatsapp")
        lead = crm.get_lead(lead_id)
    handover = HandoverService(crm)
    handover.set_mode(lead["lead_id"], "HUMAN_ACTIVE")

    message_type = "text"
    payload = text
    stored_body = text
    media_kind = media_ref = None

    if media:
        kind = media["kind"]
        mime = str(media.get("mime") or "application/octet-stream")
        filename = str(media.get("filename") or ("file." + mime.split("/")[-1]))
        raw = base64.b64decode(media["data_base64"])
        if len(raw) > 30 * 1024 * 1024:
            return {"ok": False, "error": "file too large (max 30MB)"}

        # voice notes: browser webm/opus -> WhatsApp requires ogg/amr/mp4/mpeg
        tmp_path = None
        if kind == "audio" and mime in ("audio/webm", "audio/webm;codecs=opus"):
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
                tf.write(raw)
                tmp_path = tf.name
            ogg_path = tmp_path.replace(".webm", ".ogg")
            import subprocess

            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path, "-c:a", "libopus", "-b:a", "48k", ogg_path],
                capture_output=True,
            )
            if proc.returncode == 0 and os.path.exists(ogg_path):
                raw = open(ogg_path, "rb").read()
                mime = "audio/ogg"
                filename = filename.rsplit(".", 1)[0] + ".ogg"
            else:
                mime = "audio/mp4"  # fallback container hint for Meta
            try:
                os.unlink(tmp_path)
                if os.path.exists(ogg_path):
                    os.unlink(ogg_path)
            except OSError:
                pass

        adapter = inbox.get("adapter")
        provider = getattr(adapter, "provider", None)
        upload_media = getattr(provider, "upload_media", None)
        if upload_media is None:
            # mock mode: no real upload possible — record intent only
            message_type = kind
            payload = {"caption": text, "filename": filename, "mock": True}
            media_kind, media_ref = kind, None
        else:
            media_id = upload_media(raw, mime, filename)
            message_type = kind
            payload = {"id": media_id}
            if text:
                payload["caption"] = text
            if kind == "document":
                payload["filename"] = filename
            media_kind, media_ref = kind, media_id
        stored_body = text

    if reply_to:
        if isinstance(payload, str):
            payload = {"_reply_to": reply_to, "body": payload}
        else:
            payload["_reply_to"] = reply_to

    mid = inbox["outbox"].enqueue(
        channel="whatsapp",
        recipient=wa_id,
        message_type=message_type,
        payload=payload,
        idempotency_key=f"wa-inbox:{uuid.uuid4()}",
        lead_id=lead["lead_id"],
    )
    if initiation:
        inbox["db"].execute(
            "UPDATE message_outbox SET initiation='yes' WHERE message_id=?",
            (mid,))
        inbox["db"].commit()
    results = inbox["worker"].drain(limit=5)
    sent = any(r.get("message_id") == mid and r.get("status") == "sent" for r in results)

    db = inbox["db"]
    db.execute(
        "INSERT INTO channel_messages"
        " (direction, channel, external_user_id, lead_id, body, status, created_at,"
        "  media_kind, media_ref, outbox_message_id)"
        " VALUES ('out', 'whatsapp', ?, ?, ?, ?, ?, ?, ?, ?)",
        (wa_id, lead["lead_id"], stored_body, "queued" if not sent else "sent",
         utcnow(), media_kind, media_ref, mid),
    )
    db.commit()
    audit = AuditService(db)
    audit.record("channel.inbox_send", "lead", actor="owner", result="sent" if sent else "queued")
    sync_channel_messages(db)
    row = db.execute(
        "SELECT status FROM channel_messages WHERE outbox_message_id = ?", (mid,)
    ).fetchone()
    final_status = row["status"] if row else ("sent" if sent else "queued")
    return {
        "ok": True,
        "delivered": final_status == "sent" and message_type != "text" or sent,
        "status": final_status,
        "note": None,
    }


class WebhookServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, runtime: dict):
        super().__init__(addr, WebhookRequestHandler)
        self.runtime = runtime


def serve(root: Path, host: str = "127.0.0.1", port: int = 8010) -> int:
    """S3: refuse to boot with missing secrets for enabled integrations."""
    from ..config import validate_required_env

    from ..config import load_config as _lc

    _missing = validate_required_env(_lc(root))
    if _missing:
        for item in _missing:
            log.critical("MISSING SECRET: %s", item)
        raise SystemExit(f"refusing to start — {len(_missing)} required secret(s) missing")

    from ..log import setup_logging

    setup_logging()
    runtime = build_runtime(root)
    httpd = WebhookServer((host, port), runtime)

    # owner console: Telegram natural-language remote control (owner chat only)
    console = None
    try:
        from ..ops.telegram_console import TelegramOwnerConsole

        console = TelegramOwnerConsole(runtime)
        if not console.start():
            print("telegram console disabled: missing token/chat_id", flush=True)
    except Exception as exc:  # noqa: BLE001 — console must never block serving
        log.error("telegram console failed to start: %s", exc)

    stop = {"flag": False}

    def _shutdown(signum, frame):  # noqa: ARG001
        log.info("webhook server received signal %s — shutting down", signum)
        stop["flag"] = True
        # shutdown() must run on another thread (it blocks serve_forever's thread)
        import threading

        threading.Thread(target=httpd.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _shutdown)
    log.info("webhook server listening on %s:%s (signature enforcement per config)", host, port)
    print(f"amancore webhook server listening on {host}:{port}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        if console:
            console.stop()
        httpd.server_close()
        runtime["db"].close()
        log.info("webhook server stopped cleanly")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AmanCore webhook listener")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    return serve(root, host=args.host, port=args.port)


if __name__ == "__main__":
    sys.exit(main())
