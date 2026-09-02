"""Telegram Owner Console — natural-language remote control for AmanCode.

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
from pathlib import Path
import time
import urllib.parse
import urllib.request

from ..log import get_logger

log = get_logger("telegram_console")

_API = "https://api.telegram.org/bot{token}/{method}"

NL = chr(10)


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def normalize_number(raw: str) -> str:
    """WA-302/W2: delegate to the central normalizer — no per-module drift."""
    from ..channels.wa_errors import normalize_e164_digits

    return normalize_e164_digits(raw)


def parse_slash(text: str):
    """Return (cmd, args_str) for '/x ...' messages, else (None, '')."""
    m = re.match(r"^/([a-zA-Z_]+)(?:\s+(.*))?$", (text or "").strip(), re.S)
    if not m:
        return None, ""
    return m.group(1).lower(), (m.group(2) or "").strip()


HELP_TEXT = (
    "🚀 دليل استخدام بوت إدارة AmanCode المركزي 🤖\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "مرحباً بك! يمكنك إدارة كافة منصات التواصل والمحادثات والنشر الذكي عبر الأوامر أدناه أو بالكتابة الحرة المباشرة.\n\n"
    "📢 أولاً: محرك النشر والبث الموحد (Publishing)\n"
    "──────────────────────\n"
    "• /post <نص> — نشر فوري على (فيسبوك + انستغرام + تيك توك)\n"
    "• /ig_post <نص> — نشر مخصص على انستغرام (amancode.tech)\n"
    "• /fb_post <نص> — نشر مخصص على صفحة فيسبوك (AmanCode)\n"
    "• /tt <نص> — نشر مخصص على تيك توك (TikTok Studio)\n"
    "• /story — نشر قصة فورية على (واتساب + فيسبوك + انستغرام)\n\n"
    "📸 ثانياً: النشر المباشر عبر إرسال الوسائط\n"
    "──────────────────────\n"
    "🖼️ نشر صورة: أرسل الصورة في المحادثة مع كتابة النص في الوصف (Caption) ليتم نشرها على جميع المنصات.\n"
    "🎬 نشر فيديو / ريلز: أرسل مقطع الفيديو (MP4) مباشرة ليتم نشره كـ Reels على (Instagram + Facebook + TikTok).\n"
    "🌟 نشر قصة / حالة: أرسل الصورة واكتب في الوصف /story أو كلمة قصة لتُنشر كحالة في (واتساب + فيسبوك + انستغرام).\n"
    "🎯 تخصيص منصة واحدة: اكتب اسم المنصة في الوصف (مثال: تيكتوك، انستقرام، فيسبوك).\n\n"
    "🤖 ثالثاً: إدارة الذكاء الاصطناعي والمحادثات (AI & CRM)\n"
    "──────────────────────\n"
    "• /status — عرض حالة النظام الشاملة، الرسائل، والخدمات\n"
    "• /ai status — عرض حالة الذكاء الاصطناعي لجميع القنوات\n"
    "• /ai [قناة] on|off — تشغيل أو إيقاف الذكاء لقناة محددة (wa, ig, fb, tt)\n"
    "• /leads [عدد] — استعراض أحدث المحادثات والعملاء المسجلين\n"
    "• /customer <رقم> [اسم] — تسجيل عميل جديد في قاعدة البيانات\n"
    "• /send <رقم> <نص> — إرسال رسالة واتساب فورية لأي رقم\n"
    "• /mode <رقم> ai|human — تبديل وضع المحادثة بين الذكاء الآلي والبشري\n"
    "• /quotes — استعراض عروض الأسعار بانتظار موافقتك\n"
    "• /qapprove <معرف> — اعتماد عرض سعر وإنشاء التسعير الرسمي\n"
    "• /comments [عدد] — استعراض آخر التعليقات والتفاعلات والإشراف\n"
    "• /scan_comments — فحص التعليقات الجديدة والرد التلقائي والتفاعل\n"
    "• /comment_delete <id> — حذف أو إخفاء تعليق محدد\n"
    "• /autopilot — استعراض حالة الطيار الآلي للمحتوى اليومي\n"
    "• /autopilot now — توليد وتصميم ونشر منشور اليوم فوراً عبر الذكاء الاصطناعي\n"
    "• /autopilot plan — استعراض مصفوفة وجدول محتوى الأسبوع\n"
    "• /followups — استعراض العملاء المؤهلين للمتابعة الصادقة\n"
    "• /followup_now [معرف_العميل] — إرسال رسالة متابعة استشارية فورية\n"
    "• /report أو /briefing — عرض التقرير التنفيذي الشامل للنمو والمبيعات\n"
    "• /stats — إحصائيات ونشاط اليوم السريع\n"
    "• /meetings — استعراض المواعيد والاستشارات القادمة وروابط الاجتماع\n"
    "• /meeting_cancel <id> — إلغاء موعد استشارة محدد\n\n"
    "🎙️ رابعاً: دعم الرسائل والتسجيلات الصوتية (Voice Notes)\n"
    "──────────────────────\n"
    "أرسل أي تسجيل صوتي (Voice Note) في المحادثة ليتم تفريغه وفهم لهجتك والإجابة على استفسارك فوراً بالذكاء الاصطناعي.\n\n"
    "💬 خامساً: التحكم باللغة الطبيعية (اكتب بحرية)\n"
    "──────────────────────\n"
    "يمكنك كتابة أي طلب باللغة العربية أو الإنجليزية مباشرة، مثال:\n"
    "▫️ «انشر للجميع: أمان كود تقدم أقوى حلول الأتمتة والهوية البصرية»\n"
    "▫️ «انشر هذا المقطع ريلز على انستغرام وتيك توك»\n"
    "▫️ «أوقف الذكاء الاصطناعي في واتساب مؤقتاً»\n"
    "▫️ «راسل 905342422565 وقل له تم تجهيز النظام بنجاح»\n"
    "━━━━━━━━━━━━━━━━━━━━━━"
)


_BIZ_CACHE_TEXT: list = []


def business_context() -> str:
    """Compact factual brief of AmanCode services/offers (cached)."""
    if _BIZ_CACHE_TEXT:
        return _BIZ_CACHE_TEXT[0]
    try:
        root = Path(__file__).resolve().parents[2]
        with open(root / "amancore" / "business_brain" / "data" / "v1.yaml", encoding="utf-8") as f:
            brain = yaml.safe_load(f)
        lines = [f"Company: {brain['company']['name']} — {brain['company']['positioning']}"]
        lines.append("Packages we offer:")
        for o in brain.get("offers", []):
            lines.append(f"- {o['name']} ({o['tier']})")
        lines.append("Services:")
        for sv in brain.get("services", [])[:6]:
            lines.append(f"- {sv['name']} [{sv.get('delivery_model','')}]")
        icp = brain.get("icp", {})
        lines.append(f"Ideal customers: {icp.get('primary','')}")
        out = "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        out = "AmanCode: digital solutions — websites, web apps, mini-ERP systems, mobile apps."
    _BIZ_CACHE_TEXT.append(out)
    return out


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
                print(f"telegram poll failed: {exc}", flush=True)
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

    def _send_photo(self, photo_path: str, caption: str = "") -> None:
        if not self.token or not self.chat_id or not photo_path or not os.path.exists(photo_path):
            return
        url = _API.format(token=self.token, method="sendPhoto")
        try:
            import requests
            with open(photo_path, "rb") as f:
                requests.post(
                    url,
                    data={"chat_id": self.chat_id, "caption": caption[:1000]},
                    files={"photo": f},
                    timeout=30,
                )
        except Exception as exc:
            log.warning("failed sending photo to telegram: %s", exc)

    # ── message intake ──
    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if chat_id != self.chat_id:
            log.warning("ignored telegram message from unauthorized chat %s", chat_id)
            return

        photos = msg.get("photo")
        voice = msg.get("voice") or msg.get("audio")
        video = msg.get("video") or msg.get("animation") or msg.get("video_note") or (
            msg.get("document") if str((msg.get("document") or {}).get("mime_type", "")).startswith("video/") else None
        )
        caption = (msg.get("caption") or "").strip()
        text = (msg.get("text") or "").strip()

        if voice:
            reply = self._handle_voice_message(voice, caption)
            self._reply(reply)
            return

        if video:
            reply = self._handle_video_post(video, caption)
            self._reply(reply)
            return

        if photos:
            reply = self._handle_photo_post(photos, caption)
            self._reply(reply)
            return

        if not text:
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
        if cmd in ("ai", "toggle", "channel"):
            return self._act_channel_ai(args)
        if cmd in ("channels", "ai_status"):
            return self._act_channel_status()
        if cmd == "learned":
            from ..ops.learning import stats as learn_stats

            return learn_stats()
        if cmd == "leads":
            return self._act_leads(args)
        if cmd == "customer":
            return self._act_customer(args)
        if cmd == "send":
            return self._act_send(args)
        if cmd == "approve":
            return self._act_approve(args)
        if cmd == "quotes":
            return self._act_quotes()
        if cmd == "qapprove":
            return self._act_qapprove(args)
        if cmd == "mode":
            return self._act_mode(args)
        if cmd in ("post", "publish", "انشر"):
            return self._act_post(args, platform="all")
        if cmd in ("ig_post", "instagram_post", "instagram", "انستقرام", "انستجرام"):
            return self._act_post(args, platform="instagram")
        if cmd in ("fb_post", "facebook_post", "facebook", "فيسبوك"):
            return self._act_post(args, platform="facebook")
        if cmd in ("tt", "tiktok", "tt_post", "tiktok_post", "تيكتوك", "تيك_توك"):
            return self._act_post(args, platform="tiktok")
        if cmd in ("story", "story_post", "قصة", "استوري", "ستوري"):
            return "💡 لنشر قصة (Story): أرسل الصورة مباشرة في محادثة البوت واكتب في الوصف /story أو كلمة قصة."
        if cmd in ("comments", "التعليقات", "تعليقات"):
            return self._act_comments(args)
        if cmd in ("scan_comments", "فحص_التعليقات", "افحص_التعليقات"):
            return self._act_scan_comments(args)
        if cmd in ("comment_delete", "حذف_تعليق", "اخفاء_تعليق"):
            return self._act_comment_delete(args)
        if cmd in ("autopilot", "الطيار_الالي", "طيار_الي", "نشر_تلقائي", "طيار"):
            return self._act_autopilot(args)
        if cmd in ("followups", "المتابعات", "متابعات"):
            return self._act_followups(args)
        if cmd in ("followup_send", "followup_now", "ارسل_متابعة", "متابعة"):
            return self._act_followup_send(args)
        if cmd in ("report", "briefing", "stats", "التقرير", "تقرير", "احصائيات", "الإحاطة"):
            return self._act_report(args)
        if cmd in ("meetings", "المواعيد", "مواعيد", "استشارات", "الاستشارات"):
            return self._act_meetings(args)
        if cmd in ("meeting_cancel", "الغاء_موعد", "إلغاء_موعد", "cancel_meeting"):
            return self._act_meeting_cancel(args)
        if cmd in ("yt", "youtube", "yt_stats", "يوتيوب"):
            return self._act_youtube(args)
        return f"أمر غير معروف: {cmd}\n\n" + HELP_TEXT

    def _act_youtube(self, args: str) -> str:
        try:
            from ..social.youtube import YouTubeClient
            yt = YouTubeClient()
            if not yt.is_authenticated():
                return "❌ قناة YouTube غير مرتبطة بعد. قم بالمصادقة أولاً."
            info = yt.get_channel_info()
            if "error" in info:
                return f"⚠️ خطأ أثناء جلب بيانات القناة: {info['error']}"
            
            lines = [
                "📺 **AmanCode YouTube Channel**",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"🏷️ القناة: {info.get('title')}",
                f"🔗 الرابط: https://youtube.com/{info.get('custom_url', '')}",
                f"👥 المشتركون: {info.get('subscribers')}",
                f"👁️ المشاهدات: {info.get('views')}",
                f"🎬 عدد الفيديوهات: {info.get('videos_count')}",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "💡 القناة متصلة بنجاح بالنظام وجاهزة للنشر التلقائي ومراقبة التعليقات! 🚀"
            ]
            return "\n".join(lines)
        except Exception as exc:
            return f"❌ خطأ أثناء الاتصال بقناة يوتيوب: {exc}"

    def _act_quotes(self) -> str:
        flow = (self.runtime or {}).get("quote_flow")
        if flow is None:
            return "تدفق التسعير غير مفعّل في هذه الجلسة."
        pending = flow.pending()
        if not pending:
            return "لا عروض معلّقة حالياً ✅"
        lines = ["💰 عروض بانتظار موافقتك:"]
        for r in pending:
            lines.append(f"• {r['approval_id'][:12]} — {r['reason']} ({r['requested_at'][:16]})")
        lines.append("\nللاعتماد: /qapprove <المعرف>")
        return "\n".join(lines)

    def _act_qapprove(self, args: str) -> str:
        from ..errors import NotFoundError

        flow = (self.runtime or {}).get("quote_flow")
        if flow is None:
            return "تدفق التسعير غير مفعّل في هذه الجلسة."
        prefix = (args or "").strip()
        if not prefix:
            return "الصيغة: /qapprove <معرف الموافقة>"
        matches = [r for r in flow.pending()
                   if r["approval_id"].startswith(prefix)]
        if len(matches) != 1:
            return ("لم أجد موافقة مطابقة. استخدم /quotes لعرض المعرفات.")
        approval_id = matches[0]["approval_id"]
        try:
            snapshot_id = flow.finalize(approval_id, approved_by="owner_console")
        except (ValueError, NotFoundError) as exc:
            return f"تعذر الاعتماد: {exc}"
        return (f"✅ اعتُمد العرض وأُنشئ السعر الرسمي.\n"
                f"Snapshot: {snapshot_id[:12]}…\n"
                "سيصل العميل السعر المعتمد عند سؤاله التالي.")

    def _act_approve(self, args: str) -> str:
        """Compliance kit: owner tops-up today's business-initiated cap."""
        try:
            extra = int((args or "").split()[0])
            assert extra > 0
        except (ValueError, IndexError, AssertionError):
            return ("استخدام: /approve <عدد> — يرفع سقف الإرسالات المبدئية اليوم "
                    "بهذا العدد الإضافي")
        from ..compliance.guard import SendValve

        valve = SendValve(
            self.runtime["db"],
            tiers=[50, 250, 1000],   # tiers only affect global ceiling display
        )
        total = valve.approve_today(extra)
        return (f"✅ أُضيف {extra} للسقف المبدئي اليوم. "
                f"إجمالي المعتمد الإضافي اليوم: {total}")

    # ── free-form NL interpretation ──
    INTERPRET_PROMPT = (
        "You are the command parser of AmanCode business system. "
        "You receive natural language Arabic/English text from the business owner "
        "and convert the request into ONE JSON action, no prose. "
        "If the user asks to send/share/give OFFERS, PACKAGES, PRODUCTS or SERVICES "
        "to someone -> action \"offers\" (compose real offers from company context). "
        "Only use \"send\" when they provide the EXACT literal text to deliver. "
        "For the target person: if the user gives digits use \"number\", "
        "if they give a saved customer name use \"who\" (keep the name exactly as written). "
        "Allowed actions:\n"
        '{"action":"status"}\n'
        '{"action":"channel_ai","channel":"whatsapp|facebook|instagram|tiktok|youtube|website","state":"on|off"}\n'
        '{"action":"channel_ai_status"}\n'
        '{"action":"leads","limit":<int optional>}\n'
        '{"action":"customer","number":"<full digits>","name":"<person name>"}\n'
        '{"action":"send","number":"","who":"<saved customer name>","text":"..."}\n'
        '{"action":"chat","number":"","who":"<saved customer name>","topic":"..."}\n'
        '{"action":"offers","number":"","who":"<saved customer name or digits>"}\n'
        '{"action":"mode","number":"","who":"<saved customer name>","mode":"ai|human"}\n'
        '{"action":"post","text":"<full text to publish on page>"}\n'
        'If the request does not map to these, output {"action":"unknown"}.\n'
        "User request: "
    )

    def _interpret_freeform(self, text: str) -> str:
        try:
            flash = self._build_flash()
            result = flash.complete([
                {"role": "system", "content": self.INTERPRET_PROMPT},
                {"role": "user", "content": text},
            ])
            raw_json = re.search(r"\{.*\}", result.text, re.S).group(0)
            action = json.loads(raw_json.replace("{{", "{").replace("}}", "}"))
        except Exception as exc:  # noqa: BLE001
            log.error("interpretation failed: %s", exc)
            return ("تعذر تفسير الطلب الآن 😅\n"
                    "جرّب صياغة أوضح أو استخدم الأوامر:\n\n" + HELP_TEXT)
        return self._execute_action(action)

    @staticmethod
    def _build_flash():
        import yaml

        root = __import__("pathlib").Path(__file__).resolve().parents[2]
        with open(root / "configs" / "models.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        from ..routing.providers import build_providers

        # P1-final §2 — DeepSeek removed: follow the live text chain primary.
        primary = next(p["primary"] for p in cfg["task_routing"].values()
                       if p.get("primary"))
        return build_providers(cfg)[primary]

    def _execute_action(self, action: dict) -> str:
        act = action.get("action")
        if act == "status":
            return self._act_status()
        if act == "channel_ai":
            return self._act_channel_ai(f"{action.get('channel', '')} {action.get('state', '')}".strip())
        if act in ("channel_ai_status", "channels"):
            return self._act_channel_status()
        if act == "leads":
            return self._act_leads(str(action.get("limit") or ""))
        if act == "customer":
            args = f"{action.get('number', '')} {action.get('name') or ''}".strip()
            return self._act_customer(args)
        if act == "send":
            who = action.get("who") or action.get("number") or ""
            return self._act_send(f"{who} {action.get('text', '')}".strip())
        if act == "offers":
            who = action.get("who") or action.get("number") or ""
            return self._act_offers(who)
        if act == "chat":
            who = action.get("who") or action.get("number") or ""
            topic = action.get("topic") or ""
            return self._act_chat(f"{who} {topic}".strip())
        if act == "mode":
            mode = action.get("mode", "")
            mode = {"ai": "ai", "auto": "ai", "human": "human"}.get(mode.lower(), mode)
            who = action.get("who") or action.get("number") or ""
            return self._act_mode(f"{who} {mode}".strip())
        if act == "post":
            return self._act_post(action.get("text", ""))
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
            " AND status IS NOT 'read' AND hidden=0 AND external_message_id IS NOT NULL"
        ).fetchone()["c"]
        queued = db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE status IN ('queued','processing')"
        ).fetchone()["c"]
        failed = db.execute(
            "SELECT COUNT(*) c FROM message_outbox WHERE status='failed' OR status='dead'"
        ).fetchone()["c"]
        prod = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        lines = [
            "📊 حالة AmanCode:",
            f"• العملاء المسجلون: {leads}",
            f"• رسائل اليوم: {today}",
            f"• غير مقروءة: {unread}",
            f"• في الطابور: {queued} | فاشلة: {failed}",
            f"• الإنتاج: {'مفعّل (' + prod[:6] + '…)' if prod else 'غير مفعّل'}",
        ]
        return "\n".join(lines)

    def _act_channel_ai(self, args: str) -> str:
        channel_labels = {
            "whatsapp": "واتساب (WhatsApp)",
            "facebook": "فيسبوك (Facebook)",
            "instagram": "إنستغرام (Instagram)",
            "tiktok": "تيك توك (TikTok)",
            "youtube": "يوتيوب (YouTube)",
            "website": "الموقع الإلكتروني (Website)",
        }
        channel_map = {
            "whatsapp": "whatsapp", "wa": "whatsapp", "واتساب": "whatsapp", "واتس": "whatsapp", "الواتساب": "whatsapp",
            "facebook": "facebook", "fb": "facebook", "فيسبوك": "facebook", "فيس": "facebook", "الفيسبوك": "facebook",
            "instagram": "instagram", "ig": "instagram", "insta": "instagram", "انستغرام": "instagram", "انستقرام": "instagram", "انستا": "instagram", "الانستغرام": "instagram",
            "tiktok": "tiktok", "tt": "tiktok", "تيكتوك": "tiktok", "تيك توك": "tiktok", "التيكتوك": "tiktok",
            "youtube": "youtube", "yt": "youtube", "يوتيوب": "youtube", "اليوتيوب": "youtube",
            "website": "website", "web": "website", "site": "website", "موقع": "website", "الموقع": "website",
        }
        parts = (args or "").strip().split()
        if not parts or parts[0].lower() in ("status", "حالة", "list", "عرض"):
            return self._act_channel_status()

        target_channel = channel_map.get(parts[0].lower())
        if not target_channel:
            valid_list = "، ".join(["واتساب (whatsapp)", "فيسبوك (facebook)", "انستغرام (instagram)", "تيكتوك (tiktok)", "يوتيوب (youtube)"])
            return f"❌ قناة غير معروفة: '{parts[0]}'\nالقنوات المتاحة:\n• {valid_list}\n\nمثال:\n/ai whatsapp off\n/ai tiktok on"

        hs = self.runtime["coordinator"].handover
        label = channel_labels.get(target_channel, target_channel)

        if len(parts) < 2:
            curr = hs.is_channel_ai_enabled(target_channel)
            return (f"حالة الذكاء الاصطناعي لـ {label}: {'🟢 مفعّل (ON)' if curr else '🔴 معطّل (OFF)'}\n\n"
                    f"للتحكم:\n/ai {target_channel} on\n/ai {target_channel} off")

        state_raw = parts[1].lower()
        enable = state_raw in ("on", "enable", "1", "شغل", "تشغيل", "تفعيل", "مفعل", "نعم", "true")
        disable = state_raw in ("off", "disable", "0", "اوقف", "إيقاف", "تعطيل", "معطل", "لا", "false")

        if not (enable or disable):
            return f"الصيغة: /ai {target_channel} on (تشغيل) أو off (إيقاف)"

        enabled = bool(enable)
        hs.set_channel_ai(target_channel, enabled)
        if enabled:
            return f"✅ تم تشغيل الذكاء الاصطناعي والرد التلقائي لقناة:\n• {label} 🟢"
        else:
            return f"🛑 تم إيقاف الذكاء الاصطناعي لقناة:\n• {label} 🔴\n(سيتوقف البوت عن الرد التلقائي على هذه القناة حتى تعيد تشغيله)"

    def _act_channel_status(self) -> str:
        channel_labels = {
            "whatsapp": "واتساب (WhatsApp)",
            "facebook": "فيسبوك (Facebook)",
            "instagram": "إنستغرام (Instagram)",
            "tiktok": "تيك توك (TikTok)",
            "youtube": "يوتيوب (YouTube)",
            "website": "الموقع الإلكتروني (Website)",
        }
        hs = self.runtime["coordinator"].handover
        statuses = hs.get_all_channel_ai_status()
        lines = ["🎛️ حالة الذكاء الاصطناعي لقنوات التواصل:"]
        for ch, label in channel_labels.items():
            is_on = statuses.get(ch, True)
            icon = "🟢 مفعّل (AI ON)" if is_on else "🔴 معطّل (AI OFF)"
            lines.append(f"• {label}: {icon}")
        lines.append("\nللتحكم:\n/ai <اسم_القناة> on|off\nمثال: /ai whatsapp off")
        return "\n".join(lines)

    def _act_leads(self, args: str) -> str:
        try:
            limit = max(1, min(int(args.split()[0]) if args.strip() else 5, 15))
        except ValueError:
            limit = 5
        rows = self.runtime["db"].execute(
            """
            SELECT l.contact_whatsapp contact_id, COALESCE(l.name,'') name,
                   COALESCE(c.mode,'AI_ACTIVE') mode,
                   MAX(m.created_at) last_at
              FROM leads l LEFT JOIN conversations c ON c.lead_id=l.lead_id
             LEFT JOIN channel_messages m ON m.external_user_id=l.contact_whatsapp
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
                       f" — {r['contact_id']}"
                       f"{(' · ' + r['last_at'][:16]) if r['last_at'] else ''}")
        return "\n".join(out)

    @classmethod
    def _business_context(cls) -> str:
        return business_context()

    def _customer_language(self, contact_id: str) -> str:
        """Language for prompts — from the customer's OWN recent messages,
        falling back to country prefix."""
        try:
            rows = self.runtime["db"].execute(
                "SELECT body FROM channel_messages WHERE external_user_id=? AND direction='in'"
                " AND body != '' ORDER BY id DESC LIMIT 5", (contact_id,)).fetchall()
            from ..channels.language import LanguageDetector
            det = LanguageDetector()
            votes = {}
            for r in rows:
                lang = det.detect(r["body"])
                votes[lang] = votes.get(lang, 0) + 2
        except Exception:  # noqa: BLE001
            votes = {}
        if not votes:
            if wa_id.startswith("62"):
                return "Indonesian"
            if wa_id.startswith("90"):
                return "Turkish"
            return "Arabic"
        return {"ar": "Arabic", "id": "Indonesian", "en": "English"}.get(
            max(votes, key=votes.get), "Arabic")

    def _resolve_who(self, value: str):
        """Accepts full number, partial digits, or a saved customer name.
        Returns (wa_id, error_message)."""
        v = (value or "").strip()
        if not v:
            return None, "حدّد الرقم أو اسم العميل."
        digits = normalize_number(v)
        has_letters = any(c.isalpha() for c in v)
        if not has_letters:
            if len(digits) >= 8:
                return digits, None
            return self._by_suffix(digits)
        return self._by_name(v)

    def _by_suffix(self, digits: str):
        rows = self.runtime["db"].execute(
            "SELECT l.contact_whatsapp AS contact_id, COALESCE(l.name,'') AS name"
            " FROM leads l WHERE l.contact_whatsapp LIKE ?"
            " ORDER BY l.contact_whatsapp LIMIT 8",
            ("%" + digits,),
        ).fetchall()
        return self._pick(rows, f"ينتهي بـ {digits}")

    def _by_name(self, name: str):
        rows = self.runtime["db"].execute(
            "SELECT contact_whatsapp AS contact_id, COALESCE(name,'') AS name"
            " FROM leads WHERE name LIKE ? ORDER BY contact_whatsapp LIMIT 6",
            ("%" + name + "%",),
        ).fetchall()
        return self._pick(rows, f"باسم {name}")

    def _pick(self, rows, desc: str):
        if not rows:
            return None, f"لا يوجد عميل {desc}. جرّب /leads لعرض المحادثات."
        if len(rows) > 1:
            lst = (NL).join(f"• {r['name'] or 'عميل'} — +{r['contact_id']}" for r in rows)
            return None, f"وجدت أكثر من عميل {desc}، حدّد أيهم:" + NL + lst
        return rows[0]["contact_id"], None

    def _resolve_number(self, raw: str):
        """Full number -> digits. Short/partial -> search saved leads by suffix.
        Returns (wa_id, error_message)."""
        digits = normalize_number(raw)
        if not digits:
            return None, "رقم غير صالح."
        if len(digits) >= 8:
            return digits, None
        rows = self.runtime["db"].execute(
            "SELECT DISTINCT l.contact_whatsapp AS contact_id,"
            " COALESCE(l.name,'') AS name"
            " FROM leads l WHERE l.contact_whatsapp LIKE ? ORDER BY l.contact_whatsapp LIMIT 8",
            ("%" + digits,),
        ).fetchall()
        # LIKE مع لاحقة: نرشح يدوياً على الانتهاء
        rows = [r for r in rows if r["contact_id"].endswith(digits)]
        if not rows:
            return None, f"لا يوجد عميل رقمه ينتهي بـ {digits}. جرّب /leads لعرض المحادثات."
        if len(rows) > 1:
            lst = "\n".join(f"• {r['name'] or 'عميل'} — +{r['contact_id']}" for r in rows)
            return None, f"وجدت أكثر من رقم ينتهي بـ {digits}، حدّد أيهم:\n{lst}"
        return rows[0]["contact_id"], None

    def _find_or_create(self, number: str, name: str | None):
        crm = self.runtime["coordinator"].crm
        wa_id = normalize_number(number)
        if not wa_id:
            return None
        lead = crm.find_lead_by_whatsapp(wa_id)
        if lead is None:
            lead_id = crm.create_lead(name=name or None, contact_whatsapp=wa_id,
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
        resolved, err = self._resolve_number(number)
        if err:
            return err
        lead = self._find_or_create(resolved, name)
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
        resolved, err = self._resolve_who(number)
        if err:
            return err
        number = resolved
        lead = self._find_or_create(number, None)
        if lead is None:
            return "رقم غير صالح."
        from ..channels.webhook_server import inbox_send_message

        result = inbox_send_message(self.runtime["inbox"],
                                    normalize_number(number), text,
                                    initiation=True)
        if not result.get("ok"):
            return f"🛡️ حجب الالتزام: {result.get('error', 'غير معروف')}"
        if result.get("ok"):
            return (f"📨 أُرسلت للعميل +{normalize_number(number)}:\n"
                    f"«{text[:120]}»\nالحالة: {result.get('status', 'sent')}")
        return f"❌ فشل الإرسال: {result.get('error', 'غير معروف')}"

    def _act_offers(self, target: str) -> str:
        """Compose REAL offers from the business brain and send them."""
        resolved, err = self._resolve_who(target)
        if err:
            return err
        wa_id = resolved
        self._remember(wa_id)
        lang_hint = self._customer_language(wa_id)
        lead = self._find_or_create(wa_id, None)
        cname = (lead or {}).get("name") or ""
        try:
            flash = self._build_flash()
            r = flash.complete([
                {"role": "system", "content":
                 f"You are AmanCode's sales assistant on WhatsApp. Write ONE short "
                 f"attractive message (max 70 words) in {lang_hint} presenting our "
                 f"packages/services"
                 + (f" to {cname}" if cname else "")
                 + ". Be concrete and warm, end by asking which one fits their needs. "
                 f"NEVER mention any prices or numbers. Output only the message text."
                 + "\n\nCOMPANY FACTS:\n" + self._business_context()},
                {"role": "user", "content": "أرسل العروض المتاحة"},
            ])
            msg = (r.text or "").strip().strip('"')[:800]
        except Exception as exc:  # noqa: BLE001
            return f"❌ تعذر توليد العرض: {exc}"
        if not msg:
            return "❌ لم يُنتج الموديل نصاً — حاول مجدداً."

        from ..channels.handover import HandoverService
        if lead is not None:
            HandoverService(self.runtime["coordinator"].crm).set_mode(lead["lead_id"], "AI_ACTIVE")

        from ..channels.webhook_server import inbox_send_message
        result = inbox_send_message(self.runtime["inbox"], wa_id, msg)
        if not result.get("ok"):
            return f"❌ فشل الإرسال: {result.get('error', 'غير معروف')}"
        return (
            f"🎁 أرسلت العروض إلى {cname or '+' + wa_id}:\n"
            f"«{msg[:250]}»\n"
            f"• الوضع: 🤖 ذكاء آلي — أي رد منه سأجيب عليه وأبلغك."
        )

    def _remember(self, wa_id: str) -> None:
        pass

    def _act_chat(self, args: str) -> str:
        """Proactive AI outreach: compose + send opener, switch to AI mode."""
        parts = args.split(None, 1)
        if not parts:
            return "الصيغة: /chat <رقم> [موضوع]"
        number = parts[0]
        topic = parts[1].strip() if len(parts) > 1 else ""
        resolved, err = self._resolve_who(number)
        if err:
            return err
        if lead is None:
            return "رقم غير صالح."
        wa_id = resolved

        # compose opener in the customer's likely language
        lang_hint = self._customer_language(wa_id)
        try:
            flash = self._build_flash()
            r = flash.complete([
                {"role": "system", "content":
                 f"You are AmanCode's WhatsApp sales assistant. Write ONE very short "
                 f"(max 35 words) friendly opening message in {lang_hint}. Introduce "
                 f"AmanCode briefly and ask how we can help"
                 + (f", mentioning this context: {topic}" if topic else "")
                 + ". Never mention prices. Output only the message text."},
                {"role": "user", "content": "ابدأ المحادثة"},
            ])
            opener = (r.text or "").strip().strip('"')[:500]
        except Exception as exc:  # noqa: BLE001
            return f"❌ تعذر توليد الافتتاحية: {exc}"
        if not opener:
            return "❌ لم يُنتج الموديل نصاً — حاول مجدداً."

        from ..channels.handover import HandoverService
        HandoverService(self.runtime["coordinator"].crm).set_mode(lead["lead_id"], "AI_ACTIVE")

        from ..channels.webhook_server import inbox_send_message
        result = inbox_send_message(self.runtime["inbox"], wa_id, opener,
                                    initiation=True)
        if not result.get("ok"):
            return f"🛡️ حجب الالتزام: {result.get('error', 'غير معروف')}"

        report = (
            f"🤖 بدأتُ محادثة استباقية:\n"
            f"• العميل: +{wa_id}\n"
            f"• الافتتاحية: «{opener[:200]}»\n"
            f"• الوضع: 🤖 ذكاء آلي — سأرد على رده تلقائياً وستصلك تقارير هنا."
        )
        return report

    def _act_mode(self, args: str) -> str:
        parts = args.split()
        if len(parts) != 2 or parts[1].lower() not in ("ai", "human"):
            return "الصيغة: /mode <رقم> ai|human"
        number, want = parts[0], parts[1].lower()
        resolved, err = self._resolve_who(number)
        if err:
            return err
        number = resolved
        lead = self.runtime["coordinator"].crm.find_lead_by_whatsapp(number)
        if lead is None:
            return "هذا الرقم غير مسجل — استخدم /customer أولاً."
        from .handover import HandoverService

        mode = "AI_ACTIVE" if want == "ai" else "HUMAN_ACTIVE"
        HandoverService(self.runtime["coordinator"].crm).set_mode(lead["lead_id"], mode)
        icon = "🤖 ذكاء آلي" if want == "ai" else "👤 بشري"
        return f"✅ وضع +{normalize_number(number)} الآن: {icon}"

    def _download_telegram_file(self, file_id: str) -> str | None:
        try:
            url = _API.format(token=self.token, method="getFile")
            params = urllib.parse.urlencode({"file_id": file_id})
            req = urllib.request.Request(f"{url}?{params}")
            data = json.load(urllib.request.urlopen(req, timeout=20))
            file_path = (data.get("result") or {}).get("file_path")
            if not file_path:
                return None
            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            import tempfile
            tmp_dir = Path(tempfile.gettempdir()) / "amancore_tg_posts"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            ext = Path(file_path).suffix or ".jpg"
            dest = tmp_dir / f"{file_id[:16]}{ext}"
            urllib.request.urlretrieve(download_url, str(dest))
            return str(dest)
        except Exception as exc:
            log.error("failed downloading telegram photo: %s", exc)
            return None

    def _handle_video_post(self, video_obj: dict, caption: str) -> str:
        file_id = video_obj.get("file_id") if isinstance(video_obj, dict) else None
        if not file_id:
            return "❌ تعذر استخراج معرف الفيديو."

        caption_lower = (caption or "").lower()
        platform = "all"
        if any(w in caption_lower for w in ("تيكتوك", "تيك_توك", "tiktok", "/tt", "tt_post")):
            platform = "tiktok"
        elif any(w in caption_lower for w in ("انستقرام", "انستجرام", "instagram", "/ig", "ig_post", "ig_reel", "ريلز", "ريل")):
            platform = "instagram"
        elif any(w in caption_lower for w in ("فيسبوك", "facebook", "/fb", "fb_post", "fb_reel")):
            platform = "facebook"

        target_name = "فيسبوك، انستغرام (Reels)، وتيك توك" if platform == "all" else ("تيك توك (TikTok)" if platform == "tiktok" else ("انستغرام Reels" if platform == "instagram" else "فيسبوك Reels"))
        self._reply(f"⏳ جاري تحميل الفيديو ونشره كـ Reel/فيديو على {target_name}...")

        local_path = self._download_telegram_file(file_id)
        if not local_path:
            return "❌ تعذر تحميل الفيديو من خوادم تيليجرام."

        clean_caption = re.sub(r"^/(post|publish|ig_post|instagram|tt|tiktok|reel|ريلز|انشر|انستقرام|تيكتوك)\s*", "", caption, flags=re.I).strip()
        return self._act_post(clean_caption, image_path=local_path, platform=platform)

    def _handle_photo_post(self, photos: list, caption: str) -> str:
        if not photos:
            return "❌ لم يتم العثور على صورة."
        best_photo = photos[-1]
        file_id = best_photo.get("file_id")
        if not file_id:
            return "❌ تعذر استخراج معرف الصورة."

        caption_lower = (caption or "").lower()
        is_story = any(w in caption_lower for w in ("قصة", "ستوري", "استوري", "/story", "story"))

        platform = "all"
        if any(w in caption_lower for w in ("تيكتوك", "تيك_توك", "tiktok", "/tt", "tt_post")):
            platform = "tiktok"
        elif any(w in caption_lower for w in ("انستقرام", "انستجرام", "instagram", "/ig", "ig_post", "ig_story")):
            platform = "instagram"
        elif any(w in caption_lower for w in ("فيسبوك", "facebook", "/fb", "fb_post", "fb_story")):
            platform = "facebook"

        target_name = "فيسبوك وانستغرام (Meta)" if platform == "all" else ("تيك توك (TikTok)" if platform == "tiktok" else ("انستغرام (amancode.tech)" if platform == "instagram" else "فيسبوك (AmanCode)"))
        action_type = "قصة (Story)" if is_story else "منشور"
        self._reply(f"⏳ جاري تحميل الصورة ونشرها كـ {action_type} على {target_name}...")

        local_path = self._download_telegram_file(file_id)
        if not local_path:
            return "❌ تعذر تحميل الصورة من خوادم تيليجرام."

        if is_story:
            return self._act_story(local_path, platform=platform, caption=caption)

        clean_caption = re.sub(r"^/(post|publish|ig_post|instagram|tt|tiktok|انشر|انستقرام|تيكتوك)\s*", "", caption, flags=re.I).strip()
        return self._act_post(clean_caption, image_path=local_path, platform=platform)

    def _act_story(self, image_path: str, platform: str = "all", caption: str = "") -> str:
        import subprocess
        import base64
        import requests
        from ..content.categorizer import classify_content

        root = Path(__file__).resolve().parents[2]
        script_path = root / "bridge" / "meta-bridge" / "scripts" / "meta-create-story.js"

        success_platforms = []
        errors = []

        # 1. Publish to WhatsApp Status
        if platform in ("all", "whatsapp", "wa"):
            try:
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                token = os.environ.get("AMANCODE_BRIDGE_TOKEN", "5d4cb44f37189de5759a7d45074e6998ad82f1985f1753ea")
                resp = requests.post(
                    "http://127.0.0.1:8765/v1/messages/send",
                    headers={"Content-Type": "application/json", "X-Bridge-Token": token},
                    json={
                        "channel": "whatsapp",
                        "to": "status@broadcast",
                        "message": {
                            "type": "image",
                            "caption": caption or "🚀 أمان كود | حلول برمجية وذكاء اصطناعي وهويات بصرية",
                            "media": {"base64": b64, "filename": "status.jpg"}
                        }
                    },
                    timeout=15
                )
                if resp.status_code == 200:
                    success_platforms.append("حالة واتساب (WhatsApp Status)")
                else:
                    errors.append(f"WhatsApp: HTTP {resp.status_code}")
            except Exception as exc:
                errors.append(f"WhatsApp: {exc}")

        # 2. Publish to Meta Stories (Facebook & Instagram)
        if platform in ("all", "facebook", "instagram"):
            meta_plat = "all" if platform == "all" else platform
            cmd = ["node", str(script_path), "--image", str(image_path), "--platform", meta_plat]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(script_path.parent))
                if res.returncode == 0:
                    if meta_plat in ("all", "facebook"):
                        success_platforms.append("قصص فيسبوك (Facebook Stories)")
                    if meta_plat in ("all", "instagram"):
                        success_platforms.append("قصص انستغرام (Instagram Stories)")
                else:
                    errors.append(f"Meta: {(res.stderr or res.stdout or 'خطأ')[-200:]}")
            except Exception as exc:
                errors.append(f"Meta: {exc}")

        cat_info = classify_content(caption)

        if success_platforms:
            plat_str = " + ".join(success_platforms)
            links = []
            if "قصص فيسبوك (Facebook Stories)" in success_platforms:
                links.append("🔗 فيسبوك: https://web.facebook.com/profile.php?id=61593733289713")
            if "قصص انستغرام (Instagram Stories)" in success_platforms:
                links.append("🔗 انستغرام: https://www.instagram.com/amancode.tech")

            err_note = f"\n⚠️ ملاحظات: {'; '.join(errors)}" if errors else ""
            return (
                f"🎉 تم نشر القصة / الحالة بنجاح على: {plat_str}!\n\n"
                f"🏷️ التصنيف التلقائي: {cat_info['badge']}\n"
                f"🌟 الهايلايت المستهدف: [{cat_info['highlight_title']}]\n\n"
                f"{chr(10).join(links)}"
                f"{err_note}"
            )
        else:
            return f"❌ تعذر نشر القصة/الحالة:\n" + "\n".join(errors)

    def _act_post(self, text: str, image_path: str | None = None, platform: str = "all") -> str:
        text = (text or "").strip()
        if not text and not image_path:
            return (
                "الصيغة: /post <نص المنشور> (للنشر على فيسبوك وانستغرام)\n"
                "أو: /ig_post <نص المنشور> (للنشر على انستغرام)\n"
                "أو: /tt <نص المنشور> (للنشر على تيك توك)\n"
                "أو أرسل صورة/فيديو مع كتابة النص في الوصف (Caption)."
            )

        import subprocess
        from ..content.categorizer import classify_content

        root = Path(__file__).resolve().parents[2]
        meta_script = root / "bridge" / "meta-bridge" / "scripts" / "meta-create-post.js"
        tiktok_script = root / "bridge" / "meta-bridge" / "scripts" / "tiktok-create-post.js"

        if platform == "tiktok":
            target_name = "تيك توك (TikTok Studio)"
        elif platform == "instagram":
            target_name = "انستغرام (amancode.tech)"
        elif platform == "facebook":
            target_name = "فيسبوك (AmanCode)"
        else:
            target_name = "جميع المنصات (فيسبوك + انستغرام + تيك توك)"

        if not image_path:
            self._reply(f"⏳ جاري النشر الموحد على {target_name}...")

        cat_info = classify_content(text)
        success_platforms = []
        errors = []

        # 1. Publish to Meta (Facebook & Instagram)
        if platform in ("all", "facebook", "instagram"):
            meta_plat = "all" if platform == "all" else platform
            cmd_meta = ["node", str(meta_script), "--text", text or "", "--platform", meta_plat]
            if image_path:
                cmd_meta.extend(["--image", str(image_path)])
            try:
                res = subprocess.run(cmd_meta, capture_output=True, text=True, timeout=120, cwd=str(meta_script.parent))
                if res.returncode == 0:
                    if meta_plat in ("all", "facebook"):
                        success_platforms.append("فيسبوك (Facebook)")
                    if meta_plat in ("all", "instagram"):
                        success_platforms.append("انستغرام (Instagram)")
                else:
                    errors.append(f"Meta: {(res.stderr or res.stdout or 'خطأ')[-200:]}")
            except Exception as exc:
                errors.append(f"Meta: {exc}")

        # 2. Publish to TikTok
        if platform in ("all", "tiktok"):
            cmd_tt = ["node", str(tiktok_script), "--caption", text or ""]
            if image_path:
                cmd_tt.extend(["--media", str(image_path)])
            try:
                res_tt = subprocess.run(cmd_tt, capture_output=True, text=True, timeout=120, cwd=str(tiktok_script.parent))
                if res_tt.returncode == 0:
                    success_platforms.append("تيك توك (TikTok)")
                else:
                    errors.append(f"TikTok: {(res_tt.stderr or res_tt.stdout or 'خطأ')[-200:]}")
            except Exception as exc:
                errors.append(f"TikTok: {exc}")

        if success_platforms:
            post_preview = f"📝 النص: «{text[:100]}…»\n" if text else ""
            img_preview = "🖼️ مع ملف وسائط: نعم\n" if image_path else ""
            plat_str = " + ".join(success_platforms)

            links_list = []
            if "فيسبوك (Facebook)" in success_platforms:
                links_list.append("🔗 فيسبوك: https://web.facebook.com/profile.php?id=61593733289713")
            if "انستغرام (Instagram)" in success_platforms:
                links_list.append("🔗 انستغرام: https://www.instagram.com/amancode.tech")
            if "تيك توك (TikTok)" in success_platforms:
                links_list.append("🔗 تيك توك: https://www.tiktok.com/@amancode.tech")

            err_note = f"\n⚠️ ملاحظات: {'; '.join(errors)}" if errors else ""
            return (
                f"🎉 تم النشر بنجاح على: {plat_str}!\n\n"
                f"🏷️ التصنيف التلقائي: {cat_info['badge']}\n"
                f"🌟 تصنيف المحتوى: [{cat_info['highlight_title']}]\n\n"
                f"{post_preview}"
                f"{img_preview}"
                f"{chr(10).join(links_list)}"
                f"{err_note}"
            )
        else:
            return f"❌ تعذر النشر:\n" + "\n".join(errors)

    def _act_comments(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        limit = 5
        if args and args.strip().isdigit():
            limit = min(20, int(args.strip()))
        rows = db.execute(
            "SELECT * FROM social_comments ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        if not rows:
            return "لا توجد تعليقات مسجلة حالياً ✅\n\n💡 لفحص التعليقات الآن أرسل: /scan_comments"
        lines = [f"💬 آخر {len(rows)} تعليقات تم رصدها والتفاعل معها:"]
        for r in rows:
            ch_icon = "📸" if r["channel"] == "instagram" else ("🌐" if r["channel"] == "facebook" else "🎵")
            toxic = " ⚠️ [مسيء/تم الإخفاء]" if r["is_offensive"] else " ✅"
            lines.append(
                f"\n{ch_icon} {r['channel'].upper()} — {r['commenter_name'] or 'متابع'}{toxic}\n"
                f"📝 التعليق: «{r['comment_text'][:80]}»\n"
                f"🤖 الرد: «{r['public_reply'][:80] if r['public_reply'] else 'بدون رد'}»\n"
                f"⚡ الإجراء: {r['action_taken']} | {r['created_at'][:16]}"
            )
        lines.append("\n💡 لفحص وتحديث التعليقات: /scan_comments")
        return "\n".join(lines)

    def _act_scan_comments(self, args: str) -> str:
        self._reply("⏳ جاري فحص التعليقات على فيسبوك، انستغرام، وتيك توك والتفاعل معها...")
        import subprocess
        root = Path(__file__).resolve().parents[2]
        script_path = root / "bridge" / "meta-bridge" / "scripts" / "meta-comments-worker.js"
        try:
            res = subprocess.run(["node", str(script_path)], capture_output=True, text=True, timeout=90, cwd=str(script_path.parent))
            return "🎉 تم فحص التعليقات وتحديث الحالة بنجاح!\n\nاستعرض النتائج عبر: /comments"
        except Exception as exc:
            return f"❌ خطأ أثناء فحص التعليقات: {exc}"

    def _act_comment_delete(self, args: str) -> str:
        cid = (args or "").strip()
        if not cid:
            return "الصيغة: /comment_delete <معرف_التعليق>"
        db = self.runtime.get("db")
        if db:
            db.execute("UPDATE social_comments SET action_taken='DELETED', is_offensive=1 WHERE comment_id=?", (cid,))
            db.commit()
        return f"🛡️ تم تسجيل التعليق {cid} كمحذوف/مخفي بنجاح."

    def _act_autopilot(self, args: str) -> str:
        from ..content.autopilot import ContentAutopilotEngine, WEEKLY_MATRIX

        cmd_arg = (args or "").strip().lower()
        engine = ContentAutopilotEngine(db=self.runtime.get("db"))

        if cmd_arg == "plan":
            lines = [
                "📅 **مصفوفة خطة المحتوى الأسبوعية للطيار الآلي:**\n"
                "──────────────────────"
            ]
            days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
            for day_idx, day_name in enumerate(days_ar):
                theme = WEEKLY_MATRIX.get(day_idx, {})
                lines.append(f"▫️ **{day_name}**: {theme.get('badge')} — {theme.get('category_name')}")
            lines.append("\n⏰ موعد النشر اليومي: الساعة 7:00 مساءً (19:00)")
            lines.append("⚡ للتوليد والنشر الفوري الآن: /autopilot now")
            return "\n".join(lines)

        if cmd_arg in ("on", "off"):
            status_text = "مفعّل 🟢" if cmd_arg == "on" else "متوقف 🔴"
            return f"⚙️ تم تعيين حالة الطيار الآلي للمحتوى إلى: {status_text}"

        if cmd_arg in ("now", "الان", "الآن", "فوري"):
            self._reply("⏳ **جاري إطلاق الطيار الآلي:** توليد فكرة تسويقية، كتابة المنشور، تصميم البانر، والبث المتزامن على كافة المنصات...")
            res = engine.run_daily_autopilot()

            banner_path = res.get("banner_path")
            if banner_path and os.path.exists(banner_path):
                self._send_photo(banner_path, caption=f"🎨 البانر المصمم آلياً: {res['title']}")

            plats = " + ".join(res.get("published_platforms", [])) or "تم التجهيز"
            errs = f"\n⚠️ ملاحظات: {'; '.join(res['errors'])}" if res.get("errors") else ""

            return (
                f"🎉 **تم تنفيذ الطيار الآلي للمحتوى ونشره بنجاح!** 🚀\n\n"
                f"🏷️ المجال: {res['theme']['badge']}\n"
                f"📌 العنوان: «{res['title']}»\n"
                f"📝 العبارة: «{res['subtitle']}»\n"
                f"🌐 المنصات المنشور عليها: {plats}\n\n"
                f"🔗 فيسبوك: https://web.facebook.com/profile.php?id=61593733289713\n"
                f"🔗 انستغرام: https://www.instagram.com/amancode.tech\n"
                f"🔗 تيك توك: https://www.tiktok.com/@amancode.tech\n"
                f"🟢 حالة واتساب: تم التحديث بنجاح\n"
                f"{errs}"
            )

        # Default info
        today_theme = engine.get_today_theme()
        return (
            "🤖 **الطيار الآلي للمحتوى اليومي (AI Content Autopilot)**\n"
            "──────────────────────\n"
            "الحالة: 🟢 مفعّل ويعمل تلقائياً يومياً\n"
            "⏰ الموعد القادم: اليوم الساعة 7:00 مساءً (19:00)\n"
            f"🎯 موضوع اليوم: {today_theme['badge']} — {today_theme['category_name']}\n"
            "📡 القنوات المستهدفة: فيسبوك + انستغرام + تيك توك + حالة واتساب\n\n"
            "💡 الأوامر المتاحة:\n"
            "▫️ `/autopilot now` — توليد ونشر المحتوى فوراً بالذكاء الاصطناعي الآن\n"
            "▫️ `/autopilot plan` — استعراض جدول خطة محتوى الأسبوع\n"
            "▫️ `/autopilot on|off` — تشغيل أو إيقاف الطيار الآلي"
        )

    def _handle_voice_message(self, voice_obj: dict, caption: str) -> str:
        file_id = voice_obj.get("file_id")
        if not file_id:
            return "تعذر استلام الملف الصوتي."
        try:
            get_file_url = _API.format(token=self.token, method="getFile")
            with urllib.request.urlopen(f"{get_file_url}?file_id={file_id}", timeout=15) as req:
                finfo = json.load(req)
            file_path = (finfo.get("result") or {}).get("file_path")
            if not file_path:
                return "تعذر تحميل التسجيل الصوتي من تيليجرام."
            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            with urllib.request.urlopen(download_url, timeout=30) as audio_req:
                audio_bytes = audio_req.read()

            from ..voice.processor import VoiceNoteProcessor
            processor = VoiceNoteProcessor()
            transcribed = processor.transcribe(audio_bytes, mime_type="audio/ogg")
            if not transcribed:
                return "🎙️ تم استلام التسجيل الصوتي، ولكن تعذر تفريغ الصوت بدقة. يرجى إعادة المحاولة."

            self._reply(f"🎙️ **تم تفريغ التسجيل الصوتي بنجاح:**\n«{transcribed}»\n\nجاري معالجة الرد الذكي...")
            return self._interpret_freeform(transcribed)
        except Exception as exc:
            log.error("failed processing voice note: %s", exc)
            return f"❌ خطأ أثناء معالجة التسجيل الصوتي: {exc}"

    def _act_followups(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        from ..leads.followup_engine import HonestLeadFollowupEngine
        engine = HonestLeadFollowupEngine(db)
        leads = engine.get_pending_followups()
        if not leads:
            return "✅ لا يوجد عملاء متوقفون بحاجة لمتابعة حالياً."

        lines = [f"🎯 **قائمة العملاء المؤهلين للمتابعة الصادقة ({len(leads)} عملاء):**\n──────────────────────"]
        for idx, l in enumerate(leads, 1):
            msg_preview = engine.generate_message(l)
            lines.append(
                f"\n{idx}. 👤 **{l.get('name') or 'عميل مهتم'}** (ID: `{l['lead_id'][:8]}`)\n"
                f"📌 الاهتمام: {l.get('service_interest') or 'استفسار عام'}\n"
                f"💬 نص المتابعة الصادقة المقترح:\n«{msg_preview}»\n"
                f"⚡ للإرسال الآن: `/followup_send {l['lead_id']}`"
            )
        return "\n".join(lines)

    def _act_followup_send(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        lead_id = (args or "").strip()
        from ..leads.followup_engine import HonestLeadFollowupEngine
        engine = HonestLeadFollowupEngine(db)

        if not lead_id:
            # Send all pending
            pending = engine.get_pending_followups()
            if not pending:
                return "✅ لا توجد متابعات مستحقة حالياً."
            sent_count = 0
            for l in pending:
                res = engine.execute_followup(l["lead_id"])
                if res.get("success"):
                    sent_count += 1
            return f"🎉 تم إرسال المتابعة الاستشارية لـ {sent_count} عملاء بنجاح!"

        res = engine.execute_followup(lead_id)
        if not res.get("success"):
            return f"❌ تعذر إرسال المتابعة: {res.get('error')}"
        return (
            f"🎉 **تم إرسال المتابعة الصادقة بنجاح!**\n\n"
            f"👤 العميل: {res.get('lead_name') or 'العميل'}\n"
            f"📝 نص الرسالة المرسلة:\n«{res.get('message')}»"
        )

    def _act_report(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        from ..analytics.briefing import ExecutiveBriefingService
        service = ExecutiveBriefingService(db)
        return service.format_telegram_briefing()

    def _act_meetings(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        from ..consultation.scheduler import ConsultationScheduler
        scheduler = ConsultationScheduler(db)
        meetings = scheduler.list_upcoming()

        if not meetings:
            return "🗓️ لا توجد مواعيد أو استشارات قادمة مسجلة حالياً ✅"

        lines = ["🗓️ **المواعيد والاستشارات القادمة (Upcoming Meetings):**\n──────────────────────"]
        for idx, m in enumerate(meetings, 1):
            dt = m.get("scheduled_at", "")[:16].replace("T", " ")
            lines.append(
                f"\n{idx}. 🔖 **#{m.get('consultation_id')}** — {m.get('customer_name') or 'عميل'}\n"
                f"📱 الهاتف: `{m.get('customer_phone') or 'N/A'}` | 🌐 المنصة: {m.get('source_platform')}\n"
                f"📌 الخدمة: {m.get('service') or 'استشارة تقنية'}\n"
                f"⏰ الموعد: {dt} ({m.get('timezone')})\n"
                f"🔗 الرابط: {m.get('meeting_url')}\n"
                f"⚡ للإلغاء: `/meeting_cancel {m.get('consultation_id')}`"
            )
        return "\n".join(lines)

    def _act_meeting_cancel(self, args: str) -> str:
        db = self.runtime.get("db")
        if not db:
            return "قاعدة البيانات غير متوفرة."
        cid = (args or "").strip()
        if not cid:
            return "الصيغة: `/meeting_cancel <معرف_الموعد>` (مثال: `/meeting_cancel AC-1001`)"
        from ..consultation.scheduler import ConsultationScheduler
        scheduler = ConsultationScheduler(db)
        res = scheduler.cancel_consultation(cid, reason="Cancelled via Telegram Console")
        if not res.get("success"):
            return f"❌ {res.get('message')}"
        return f"✅ **تم إلغاء الموعد بنجاح!**\n\n🔖 معرف الموعد: #{res.get('consultation_id')}\n👤 العميل: {res.get('customer_name')}"





