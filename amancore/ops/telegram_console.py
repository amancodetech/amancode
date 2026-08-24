"""Telegram Owner Console — natural-language remote control for AmanCore.

Owner-only bot: polls getUpdates, verifies the sender is the configured
TELEGRAM_CHAT_ID, then executes whitelisted actions against the live runtime.
Slash commands work directly; free-form Arabic/English text is interpreted
by the model router into a whitelisted action JSON before execution.

Secrets come from env only. Never executes anything from unverified chats.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from ..log import get_logger

log = get_logger("telegram_console")

_API = "https://api.telegram.org/bot{token}/{method}"


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def normalize_number(raw: str) -> str:
    """Keep digits only; drop leading zeros/+ (Graph API wants digits)."""
    digits = re.sub(r"\D", "", raw or "")
    return digits.lstrip("0")


def parse_slash(text: str):
    """Return (cmd, args_str) for '/x ...' messages, else (None, '')."""
    m = re.match(r"^/([a-zA-Z_]+)(?:\s+(.*))?$", (text or "").strip(), re.S)
    if not m:
        return None, ""
    return m.group(1).lower(), (m.group(2) or "").strip()


HELP_TEXT = (
    "🤖 AmanCore Console — الأوامر:\n"
    "/status — حالة النظام\n"
    "/leads [عدد] — آخر المحادثات\n"
    "/customer <رقم> [اسم] — تسجيل عميل جديد\n"
    "/send <رقم> <نص> — إرسال واتساب فوري\n"
    "/mode <رقم> ai|human — تبديل وضع الرد\n"
    "\nأو اكتب بأي لغة طلباً حراً، مثال:\n"
    "\"راسل 905342422565 وقل له عرضنا الجديد جاهز\"\n"
    "\"سجل الرقم 62812345 باسم أحمد كعميل\""
)


class TelegramOwnerConsole:
    """Long-polling owner console wired to the live runtime."""

    def __init__(self, runtime: dict, poll_timeout: int = 25):
        self.runtime = runtime
        self.poll_timeout = poll_timeout
        self.token = _env("TELEGRAM_BOT_TOKEN")
        self.chat_id = _env("TELEGRAM_CHAT_ID")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0

    # ── lifecycle ──
    def available(self) -> bool:
        return bool(self.token and self.chat_id)

    def start(self) -> bool:
        if not self.available():
            log.info("telegram console disabled (TELEGRAM_BOT_TOKEN/CHAT_ID unset)")
            return False
        self._thread = threading.Thread(target=self._run, name="tg-console", daemon=True)
        self._thread.start()
        log.info("telegram owner console started")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.poll_timeout + 5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for upd in self._poll():
                    try:
                        self._handle_update(upd)
                    except Exception as exc:  # noqa: BLE001 — one bad update must not kill polling
                        log.error("update handling failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.error("telegram poll failed: %s", exc)
                time.sleep(5)

    def _poll(self) -> list:
        url = _API.format(token=self.token, method="getUpdates")
        params = urllib.parse.urlencode({
            "timeout": self.poll_timeout,
            "offset": self._offset,
            "allowed_updates": json.dumps(["message"]),
        })
        data = json.load(urllib.request.urlopen(f"{url}?{params}", timeout=self.poll_timeout + 10))
        result = data.get("result", [])
        if result:
            self._offset = result[-1]["update_id"] + 1
        return result

    def _reply(self, text: str) -> None:
        url = _API.format(token=self.token, method="sendMessage")
        body = json.dumps({
            "chat_id": self.chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30)

    # ── message intake ──
    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if chat_id != self.chat_id:
            log.warning("ignored telegram message from unauthorized chat %s", chat_id)
            return
        cmd, args = parse_slash(text)
        if cmd:
            reply = self._dispatch(cmd, args)
        else:
            reply = self._interpret_freeform(text)
        self._reply(reply)

    # ── slash commands ──
    def _dispatch(self, cmd: str, args: str) -> str:
        if cmd in ("start", "help"):
            return HELP_TEXT
        if cmd == "status":
            return self._act_status()
        if cmd == "leads":
            return self._act_leads(args)
        if cmd == "customer":
            return self._act_customer(args)
        if cmd == "send":
            return self._act_send(args)
        if cmd == "mode":
            return self._act_mode(args)
        return f"أمر غير معروف: {cmd}\n\n" + HELP_TEXT

    # ── free-form NL interpretation ──
    INTERPRET_PROMPT = (
        "You are the command parser of AmanCore business system. "
        "Convert the user request into ONE JSON action, no prose. "
        "Allowed actions:\n"
        '{{"action":"status"}}\n'
        '{{"action":"leads","limit":<int optional>}}\n'
        '{{"action":"customer","number":"<digits>","name":"<optional>"}}\n'
        '{{"action":"send","number":"<digits>","text":"<message body>"}}\n'
        '{{"action":"mode","number":"<digits>","mode":"ai|human"}}\n'
        'If the request does not map to these, output {{"action":"unknown"}}.\n'
        "User request: "
    )

    def _interpret_freeform(self, text: str) -> str:
        try:
            flash = self._build_flash()
            result = flash.complete([
                {"role": "system", "content": self.INTERPRET_PROMPT},
                {"role": "user", "content": text},
            ])
            action = json.loads(re.search(r"\{.*\}", result.text, re.S).group(0))
        except Exception as exc:  # noqa: BLE001
            log.error("interpretation failed: %s", exc)
            return ("تعذر تفسير الطلب الآن 😅\n"
                    "جرّب صياغة أوضح أو استخدم الأوامر:\n\n" + HELP_TEXT)
        return self._execute_action(action)

    @staticmethod
    def _build_flash():
        import yaml

        root = __import__("pathlib").Path(__file__).resolve().parents[2]
        cfg = yaml.safe_load(open(root / "configs" / "models.yaml"))
        from ..routing.providers import build_providers

        return build_providers(cfg)["deepseek-v4-flash"]

    def _execute_action(self, action: dict) -> str:
        act = action.get("action")
        if act == "status":
            return self._act_status()
        if act == "leads":
            return self._act_leads(str(action.get("limit") or ""))
        if act == "customer":
            args = f"{action.get('number', '')} {action.get('name') or ''}".strip()
            return self._act_customer(args)
        if act == "send":
            return self._act_send(
                f"{action.get('number', '')} {action.get('text', '')}".strip())
        if act == "mode":
            mode = action.get("mode", "")
            mode = {"ai": "ai", "auto": "ai", "human": "human"}.get(mode.lower(), mode)
            return self._act_mode(f"{action.get('number', '')} {mode}".strip())
        return "هذا الطلب خارج صلاحياتي حالياً.\n\n" + HELP_TEXT

    # ── actions (all read/write the LIVE runtime) ──
    def _act_status(self) -> str:
        db = self.runtime["db"]
        leads = db.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        today = db.execute(
            "SELECT COUNT(*) c FROM channel_messages WHERE date(created_at)=date('now')"
        ).fetchone()["c"]
        unread = db.execute(
            "SELECT COUNT(*) c FROM channel_messages WHERE direction='in'"
            " AND status IS NOT 'read' AND hidden=0 AND wa_message_id LIKE 'wamid.%'"
        ).fetchone()["c"]
        queued = db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE status IN ('queued','processing')"
        ).fetchone()["c"]
        failed = db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE status='failed' OR status='dead'"
        ).fetchone()["c"]
        prod = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        lines = [
            "📊 حالة AmanCore:",
            f"• العملاء المسجلون: {leads}",
            f"• رسائل اليوم: {today}",
            f"• غير مقروءة: {unread}",
            f"• في الطابور: {queued} | فاشلة: {failed}",
            f"• الإنتاج: {'مفعّل (' + prod[:6] + '…)' if prod else 'غير مفعّل'}",
        ]
        return "\n".join(lines)

    def _act_leads(self, args: str) -> str:
        try:
            limit = max(1, min(int(args.split()[0]) if args.strip() else 5, 15))
        except ValueError:
            limit = 5
        rows = self.runtime["db"].execute(
            """
            SELECT l.contact_whatsapp wa_id, COALESCE(l.name,'') name,
                   COALESCE(c.mode,'AI_ACTIVE') mode,
                   MAX(m.created_at) last_at
              FROM leads l LEFT JOIN conversations c ON c.lead_id=l.lead_id
             LEFT JOIN channel_messages m ON m.wa_id=l.contact_whatsapp
             GROUP BY l.contact_whatsapp ORDER BY last_at DESC NULLS LAST LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if not rows:
            return "لا يوجد عملاء بعد."
        icon = {"AI_ACTIVE": "🤖", "AI_RESUMED": "🤖", "HUMAN_ACTIVE": "👤",
                "HUMAN_REQUESTED": "⏳"}
        out = ["👥 آخر المحادثات:"]
        for r in rows:
            out.append(f"• {icon.get(r['mode'], '❔')} {r['name'] or 'عميل'}"
                       f" — {r['wa_id']}"
                       f"{(' · ' + r['last_at'][:16]) if r['last_at'] else ''}")
        return "\n".join(out)

    def _find_or_create(self, number: str, name: str | None):
        crm = self.runtime["coordinator"].crm
        wa_id = normalize_number(number)
        if not wa_id:
            return None
        lead = crm.find_lead_by_whatsapp(wa_id)
        if lead is None:
            lead_id = crm.create_lead(contact_whatsapp=wa_id,
                                      source_channel="whatsapp")
            lead = crm.get_lead(lead_id)
        elif name:
            try:
                crm.update_lead(lead["lead_id"], name=name)
                lead = crm.get_lead(lead["lead_id"])
            except TypeError:
                pass
        return lead

    def _act_customer(self, args: str) -> str:
        parts = args.split(None, 1)
        if not parts:
            return "الصيغة: /customer <رقم> [اسم]"
        number = parts[0]
        name = parts[1].strip() if len(parts) > 1 else None
        lead = self._find_or_create(number, name)
        if lead is None:
            return "رقم غير صالح."
        return (f"✅ العميل مسجل:\n"
                f"• الاسم: {lead.get('name') or name or '—'}\n"
                f"• الرقم: +{normalize_number(number)}\n"
                f"• المعرف: {lead['lead_id']}")

    def _act_send(self, args: str) -> str:
        m = re.match(r"^(\S+)\s+(.+)$", args, re.S)
        if not m:
            return "الصيغة: /send <رقم> <نص>"
        number, text = m.group(1), m.group(2).strip()
        lead = self._find_or_create(number, None)
        if lead is None:
            return "رقم غير صالح."
        from ..channels.webhook_server import inbox_send_message

        result = inbox_send_message(self.runtime["inbox"],
                                    normalize_number(number), text)
        if result.get("ok"):
            return (f"📨 أُرسلت للعميل +{normalize_number(number)}:\n"
                    f"«{text[:120]}»\nالحالة: {result.get('status', 'sent')}")
        return f"❌ فشل الإرسال: {result.get('error', 'غير معروف')}"

    def _act_mode(self, args: str) -> str:
        parts = args.split()
        if len(parts) != 2 or parts[1].lower() not in ("ai", "human"):
            return "الصيغة: /mode <رقم> ai|human"
        number, want = parts[0], parts[1].lower()
        lead = self.runtime["coordinator"].crm.find_lead_by_whatsapp(normalize_number(number))
        if lead is None:
            return "هذا الرقم غير مسجل — استخدم /customer أولاً."
        from .handover import HandoverService

        mode = "AI_ACTIVE" if want == "ai" else "HUMAN_ACTIVE"
        HandoverService(self.runtime["coordinator"].crm).set_mode(lead["lead_id"], mode)
        icon = "🤖 ذكاء آلي" if want == "ai" else "👤 بشري"
        return f"✅ وضع +{normalize_number(number)} الآن: {icon}"
