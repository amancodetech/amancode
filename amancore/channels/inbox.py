"""Private owner inbox — hidden, authenticated web UI for WhatsApp conversations.

Security model (defense in depth):
    - hidden URL path segment (INBOX_PATH_SLUG) — never linked publicly
    - PBKDF2-SHA256 password verification (INBOX_PASSWORD_HASH), constant-time compare
    - HMAC-signed session cookie with expiry (INBOX_SECRET)
    - per-IP login rate limiting (in-memory)
    - security headers: noindex / no-store / X-Frame-Options DENY

All outbound sends go through MessageOutbox -> ChannelPolicyEngine -> provider
(production gate still applies). Owner replies switch the conversation to
HUMAN_ACTIVE so the AI stops auto-replying.

Standard library only. Secrets come from environment only.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from http import cookies as http_cookies

SESSION_COOKIE = "amancore_inbox"
SESSION_TTL_SECONDS = 12 * 60 * 60
PBKDF2_ITERATIONS = 200_000


# ── password hashing ────────────────────────────────────────────────────────


def hash_password(password: str, salt: str | None = None) -> str:
    """Return 'pbkdf2$iterations$salt_hex$hash_hex' for storing in env."""
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    )
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt_hex}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ── signed session cookie ───────────────────────────────────────────────────


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session_token(secret: str, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + SESSION_TTL_SECONDS)
    nonce = secrets.token_hex(8)
    payload = f"{expires}.{nonce}"
    return f"{payload}.{_sign(secret, payload)}"


def verify_session_token(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token or token.count(".") != 2:
        return False
    expires_str, nonce, signature = token.split(".")
    payload = f"{expires_str}.{nonce}"
    expected = _sign(secret, payload)
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        return int(expires_str) > int(now if now is not None else time.time())
    except ValueError:
        return False


def extract_session_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar = http_cookies.SimpleCookie()
    try:
        jar.load(cookie_header)
    except http_cookies.CookieError:
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


# ── login rate limiting ─────────────────────────────────────────────────────


class LoginRateLimiter:
    """Sliding-window failure counter per key (IP). Lockout after threshold."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 600):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    MAX_TRACKED_KEYS = 10_000   # S2: bound attacker-controlled key growth

    def _prune(self, current: float) -> None:
        stale = [k for k, v in self._failures.items()
                 if not v or current - v[-1] >= self.window_seconds]
        for k in stale:
            del self._failures[k]
        if len(self._failures) > self.MAX_TRACKED_KEYS:   # flood guard
            keep = sorted(self._failures.items(),
                          key=lambda kv: kv[1][-1], reverse=True)[:self.MAX_TRACKED_KEYS]
            self._failures.clear()
            self._failures.update(keep)

    def is_locked(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        with self._lock:
            self._prune(current)
            stamps = [t for t in self._failures.get(key, []) if current - t < self.window_seconds]
            self._failures[key] = stamps
            return len(stamps) >= self.max_failures

    def record_failure(self, key: str, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            self._failures.setdefault(key, []).append(current)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# ── configuration ───────────────────────────────────────────────────────────


class InboxConfigError(RuntimeError):
    pass


class InboxConfig:
    """Reads inbox settings from environment (never hardcoded)."""

    def __init__(self, env: dict | None = None):
        e = dict(os.environ if env is None else env)
        self.slug = e.get("INBOX_PATH_SLUG", "").strip()
        self.password_hash = e.get("INBOX_PASSWORD_HASH", "").strip()
        self.secret = e.get("INBOX_SECRET", "").strip()
        # S2: trust proxy IP headers ONLY when explicitly deployed behind one;
        # Secure cookie only when served over HTTPS (public) — LAN http needs it off
        self.trust_proxy_ip = e.get("INBOX_TRUST_PROXY_IP", "").strip().lower() in {"1", "true", "yes"}
        self.secure_cookie = e.get("INBOX_SECURE_COOKIE", "").strip().lower() in {"1", "true", "yes"}

    @property
    def configured(self) -> bool:
        return bool(self.slug and self.password_hash and self.secret)

    @property
    def login_path(self) -> str:
        return f"/{self.slug}/login"

    @property
    def app_path(self) -> str:
        return f"/{self.slug}/app"


# ── HTML rendering (escaped, minimal, RTL Arabic UI) ────────────────────────


_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # S4: lock page capabilities down; inline style kept for the legacy UI
    # until UI-403, script-src 'self' only.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


def security_headers() -> dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    headers["X-Robots-Tag"] = "noindex, nofollow"
    return headers


_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow"><title>·</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>💬</text></svg>">
<style>
body{{font-family:system-ui,sans-serif;background:#101c30;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
form{{background:#f7f3ea;padding:2rem;border-radius:12px;width:min(320px,90vw);box-shadow:0 10px 40px rgba(0,0,0,.4)}}
h1{{font-size:1.1rem;margin:0 0 1rem;color:#101c30}}
input{{width:100%;padding:.6rem;border:1px solid #c9a86a;border-radius:6px;margin-bottom:.8rem;box-sizing:border-box;font-size:1rem}}
button{{width:100%;padding:.6rem;background:#101c30;color:#c9a86a;border:0;border-radius:6px;font-size:1rem;cursor:pointer}}
.err{{color:#b00020;font-size:.85rem;margin-bottom:.6rem}}
</style></head><body><form method="post" action="{action}">
<h1>🔒 AmanCode Inbox</h1>
{error}
<input type="password" name="password" placeholder="كلمة المرور" autofocus required autocomplete="current-password">
<button type="submit">دخول</button></form></body></html>"""


def render_login_page(action_path: str, error: str = "") -> str:
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return _LOGIN_PAGE.format(action=html.escape(action_path), error=err_html)


_INBOX_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow"><title>AmanCode Inbox</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>💬</text></svg>">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0b141a;height:100vh;display:flex}}
aside{{width:min(340px,38vw);background:#111b21;color:#e9edef;display:flex;flex-direction:column;border-left:1px solid #2a3942}}
aside .panel-head{{padding:.9rem 1rem;background:#202c33;font-weight:600;font-size:1rem;border-bottom:1px solid #2a3942}}
#leads{{flex:1;overflow-y:auto}}
.lead{{display:flex;gap:.7rem;padding:.65rem .9rem;cursor:pointer;border-bottom:1px solid #222d34;align-items:center}}
.lead:hover{{background:#202c33}} .lead.sel{{background:#2a3942}}
.avatar{{width:44px;height:44px;border-radius:50%;background:#676f73;display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:600;color:#111b21;flex-shrink:0}}
.lead-info{{flex:1;min-width:0}}
.lead-name{{font-size:.95rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.lead-sub{{font-size:.78rem;color:#8696a0;direction:ltr;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.mode-chip{{font-size:.62rem;padding:.1rem .45rem;border-radius:10px;background:#3b4a54;color:#8696a0;margin-right:.35rem}}
.mode-chip.human{{background:#1f6b49;color:#c9f0d2}}
main{{flex:1;display:flex;flex-direction:column;background:#0b141a;
 background-image:radial-gradient(#182229 1px,transparent 1px);background-size:22px 22px}}
header{{padding:.65rem 1rem;background:#202c33;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2a3942}}
#who{{color:#e9edef;font-weight:600;font-size:.95rem}}
header form button{{background:none;border:1px solid #667781;color:#8696a0;border-radius:20px;padding:.3rem .9rem;cursor:pointer;font-size:.8rem}}
header form button:hover{{background:#2a3942}}
#log{{flex:1;overflow-y:auto;padding:1.2rem 4%;display:flex;flex-direction:column;gap:.3rem}}
.msg{{max-width:72%;padding:.45rem .7rem .3rem;border-radius:8px;font-size:.93rem;line-height:1.45;
 white-space:pre-wrap;word-break:break-word;position:relative;box-shadow:0 1px 1px rgba(0,0,0,.2)}}
.in{{background:#202c33;color:#e9edef;align-self:flex-start;border-top-right-radius:0}}
.out{{background:#005c4b;color:#e9edef;align-self:flex-end;border-top-left-radius:0}}
.meta{{display:flex;justify-content:flex-end;align-items:center;gap:.25rem;font-size:.65rem;color:#8696a0;margin-top:.15rem}}
.msg.out .meta{{color:#8fd0bd}}
.tick{{color:#8696a0;font-weight:bold}}
.tick.blue{{color:#53bdeb}}
.day{{align-self:center;background:#182229;color:#8696a0;font-size:.72rem;padding:.25rem .8rem;border-radius:8px;margin-bottom:.5rem}}
.empty{{color:#8696a0;text-align:center;margin-top:3rem;font-size:.9rem}}
#composer{{display:none;gap:.5rem;padding:.6rem .8rem;background:#202c33;align-items:center}}
#composer.on{{display:flex}}
#text{{flex:1;padding:.7rem 1rem;border:0;border-radius:10px;background:#2a3942;color:#e9edef;font-size:1rem;outline:none}}
#send{{width:44px;height:44px;border-radius:50%;border:0;background:#00a884;color:#fff;font-size:1.2rem;cursor:pointer;flex-shrink:0}}
#attach,#mic,#emojibtn{{width:40px;height:40px;border-radius:50%;border:0;background:#2a3942;font-size:1rem;cursor:pointer;flex-shrink:0}}
#mic.recording{{background:#dc3545;animation:pulse 1s infinite}}
@keyframes pulse{{50%{{opacity:.6}}}}
.media-img{{max-width:260px;border-radius:8px;display:block}}
.media-vid{{max-width:280px;border-radius:8px;display:block}}
audio{{max-width:250px;height:38px}}
.doc{{display:flex;align-items:center;gap:.4rem;background:rgba(255,255,255,.08);padding:.4rem .6rem;border-radius:6px;font-size:.88rem}}
#preview{{padding:.5rem .8rem;background:#202c33;display:flex;justify-content:space-between;align-items:center;color:#e9edef;font-size:.85rem}}
#replybar{{display:none;padding:.4rem .8rem;background:#1f2c33;border-top:1px solid #2a3942;color:#8696a0;font-size:.8rem;justify-content:space-between;align-items:center}}
#replybar .q{{color:#e9edef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-right:.5rem}}
#replybar button{{background:none;border:0;color:#f15c6d;cursor:pointer;font-size:.9rem}}
.msg:hover{{filter:brightness(1.12)}}
.acts,.reactbar{{position:absolute;top:-14px;left:6px;display:none;background:#233138;border-radius:14px;padding:.1rem .35rem;z-index:5}}
.msg:hover .acts,.msg:hover .reactbar,.msg.open .acts,.msg.open .reactbar{{display:flex}}
#composer{{position:relative}}
#emojiPanel{{position:absolute;bottom:105%;left:8px;right:8px;max-width:360px;height:300px;background:#233138;border:1px solid #2a3942;border-radius:14px;display:none;flex-direction:column;z-index:60;box-shadow:0 -6px 24px rgba(0,0,0,.45);overflow:hidden}}
#emojiPanel.open{{display:flex}}
.ep-tabs{{display:flex;border-bottom:1px solid #111b21;background:#1f2c33}}
.ep-tabs button{{flex:1;background:none;border:0;font-size:1.05rem;padding:.4rem 0;cursor:pointer;opacity:.5;border-bottom:2px solid transparent}}
.ep-tabs button.on{{opacity:1;border-bottom-color:#00a884;background:#233138}}
.ep-grid{{display:grid;grid-template-columns:repeat(8,1fr);gap:.1rem;padding:.45rem;overflow-y:auto;flex:1;margin:0}}
.ep-grid button{{background:none;border:0;font-size:1.3rem;cursor:pointer;border-radius:8px;padding:.12rem;line-height:1.3}}
.ep-grid button:hover{{background:#2a3942}}
.qreact{{position:absolute;top:-11px;left:4px;display:flex;align-items:center;justify-content:center;border:1px solid #374248;background:#233138;border-radius:50%;width:24px;height:24px;font-size:.72rem;cursor:pointer;opacity:.9;z-index:4}}
.qreact:hover{{transform:scale(1.15)}}
.quotebox{{background:#2a3942;border-right:3px solid #06cf9c;border-radius:6px;padding:.25rem .5rem;margin-bottom:.25rem;color:#8696a0;font-size:.75rem;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.rx{{position:absolute;bottom:-10px;left:-4px;background:#233138;border:1px solid #374248;border-radius:50%;padding:.1rem .25rem;font-size:.7rem;z-index:4}}
.unread{{background:#25d366;color:#111b21;font-size:.7rem;font-weight:700;border-radius:50%;min-width:18px;height:18px;display:flex;align-items:center;justify-content:center;padding:0 4px;margin-left:auto;flex-shrink:0}}
.msg.in{{cursor:pointer}}
.acts button{{border:0;background:none;cursor:pointer;font-size:.85rem;padding:.1rem .3rem}}
.reactbar button{{border:0;background:none;cursor:pointer;font-size:.95rem;padding:.05rem}}
#preview button{{background:none;border:0;color:#f15c6d;font-size:1rem;cursor:pointer}}
#send:hover{{background:#06cf9c}}
#attach:hover,#mic:hover,#emojibtn:hover{{background:#374248}}
@media(max-width:700px){{aside{{width:100%;display:none}} aside.open{{display:flex}}
 body.chatting aside{{display:none}} main{{display:none}} body.chatting main{{display:flex}}}}
#back{{display:none;background:none;border:0;color:#aebac1;font-size:1.4rem;cursor:pointer;margin-left:.3rem}}
@media(max-width:900px){{body.chatting #back{{display:inline-block}}}}
#sendStatus{{position:fixed;bottom:84px;right:50%;transform:translateX(50%);background:#233138;color:#e9edef;padding:.45rem .9rem;border-radius:18px;font-size:.85rem;z-index:80;box-shadow:0 4px 14px rgba(0,0,0,.4)}}
.loadOlder{{margin:.5rem auto;display:block;background:#202c33;border:1px solid #2a3942;color:#8696a0;border-radius:14px;padding:.35rem .9rem;cursor:pointer}}
::-webkit-scrollbar{{width:6px}} ::-webkit-scrollbar-thumb{{background:#374248;border-radius:3px}}
</style></head><body>
<aside id="leadsPanel"><div class="panel-head">💬 المحادثات</div><div id="leads"><div class="empty">لا محادثات بعد</div></div></aside>
<main id="chatArea">
<header><button id="back" type="button" title="عودة">←</button><span id="who">AmanCode Inbox</span><form method="post" action="{logout}"><button>خروج ⏻</button></form></header>
<div id="log"><div class="empty">اختر محادثة من القائمة لعرض الرسائل</div></div>
<div id="replybar"><span class="q"></span><button type="button">✕</button></div>
<form id="composer">
<input type="file" id="file" hidden>
<button type="button" id="attach" title="مرفق">📎</button>
<button type="button" id="mic" title="تسجيل صوتي">🎤</button>
<button type="button" id="emojibtn" title="إيموجي">😊</button>
<input id="text" placeholder="اكتب رسالة…" autocomplete="off">
<button id="send">➤</button>
<div id="emojiPanel"><div class="ep-tabs" id="epTabs"></div><div class="ep-grid" id="epGrid"></div></div>
</form>
<div id="preview" hidden><span id="preview-info"></span><button id="preview-cancel">✕</button></div>
<div id="sendStatus" hidden></div>
</main>
<script>
const LEADS=document.getElementById('leads'),LOG=document.getElementById('log'),
WHO=document.getElementById('who'),TEXT=document.getElementById('text'),
FILE=document.getElementById('file'),PREVIEW=document.getElementById('preview');
let current=null,timer=null,pendingMedia=null,pendingReply=null,recorder=null,chunks=[];
let msgToken=0,lastMsgsHash=null,oldestId=null,toastTimer=null;
function showToast(t){{const el=document.getElementById('sendStatus');el.textContent=t;el.hidden=false;
 clearTimeout(toastTimer);toastTimer=setTimeout(()=>{{el.hidden=true}},4000)}}
function hideToast(){{const el=document.getElementById('sendStatus');clearTimeout(toastTimer);el.hidden=true}}
document.getElementById('back').onclick=()=>{{document.body.classList.remove('chatting');current=null;
 lastMsgsHash=null;oldestId=null;syncComposer();}};
function esc(s){{const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}}
function fmtSize(n){{return n>1048576?(n/1048576).toFixed(1)+' MB':Math.ceil(n/1024)+' KB'}}
function syncComposer(){{
 const c=document.getElementById('composer'),rb=document.getElementById('replybar'),
 pv=document.getElementById('preview');
 if(current){{c.classList.add('on')}}
 else{{c.classList.remove('on');rb.style.display='none';pv.hidden=true;
  pendingReply=null;pendingMedia=null;c.reset();}}}}
async function loadLeads(){{
 const r=await fetch('{base}/api/leads');if(r.status===403)location.reload();
 const d=await r.json();
 if(!d.length){{LEADS.innerHTML='<div class="empty">لا محادثات بعد<br>ستظهر هنا رسائل العملاء تلقائيًا</div>';return}}
 LEADS.innerHTML='';
 d.forEach(l=>{{
  const el=document.createElement('div');el.className='lead'+(l.wa_id===current?' sel':'');
  const initial=esc((l.name||l.wa_id||'?').trim()[0]||'?').toUpperCase();
  const human=(l.mode==='HUMAN_ACTIVE'||l.mode==='HUMAN_REQUESTED');
  const ub=(l.unread>0)?'<span class="unread">'+(l.unread>99?'99+':l.unread)+'</span>':'';
  el.innerHTML='<div class="avatar">'+initial+'</div>'+
   '<div class="lead-info"><div class="lead-name">'+esc(l.name||'عميل')+
   '<span class="mode-chip'+(human?' human':'')+'">'+(human?'👤 بشري':'🤖 AI')+'</span></div>'+
   '<div class="lead-sub">'+esc(l.wa_id)+(l.last_at?' · '+esc(l.last_at.slice(5,16)):'')+'</div></div>'+ub;
  el.onclick=()=>{{
   current=l.wa_id;WHO.textContent=(l.name||'')+' · '+l.wa_id;
   document.querySelectorAll('.lead').forEach(x=>x.classList.remove('sel'));el.classList.add('sel');
   document.body.classList.add('chatting');syncComposer();loadMsgs();TEXT.focus()}};
  LEADS.appendChild(el);
 }});}}
function ticks(m){{
 if(m.direction!=='out')return '';
 const s=m.status||'queued';
 if(s==='read')return '<span class="tick blue">✓✓</span>';
 if(s==='delivered')return '<span class="tick">✓✓</span>';
 if(s==='sent'||s==='processing')return '<span class="tick">✓</span>';
 if(s==='failed'||s==='dead')return '<span style="color:#f15c6d">✗ '+esc(s)+'</span>';
 return '<span>🕐</span>';}}
function mediaHtml(m){{
 const md=m.media||{{}};const kind=md.kind;const ref=md.ref||'';
 if(kind==='image'&&ref)return '<img class="media-img" src="{base}/api/media?ref='+encodeURIComponent(ref)+'" loading="lazy">';
 if(kind==='audio'&&ref)return '<audio controls preload="none" src="{base}/api/media?ref='+encodeURIComponent(ref)+'"></audio>';
 if(kind==='video'&&ref)return '<video controls preload="none" src="{base}/api/media?ref='+encodeURIComponent(ref)+'" class="media-vid"></video>';
 if(kind==='document')return '<div class="doc">📄 '+(md.filename?esc(md.filename):'ملف')+'</div>';
 return '';}}
async function loadMsgs(force=false){{
 if(!current)return;
 const tok=++msgToken,wa=current;
 const r=await fetch('{base}/api/messages?wa_id='+encodeURIComponent(wa));
 if(r.status===403)location.reload();
 if(tok!==msgToken||wa!==current)return;               // U2: stale-response discard
 if(!r.ok){{showToast('✗ فشل تحميل الرسائل');return}}
 const d=await r.json();
 const sig=d.length+'|'+(d.length?d[0].id+'..'+d[d.length-1].id+':'+d[d.length-1].status:'');
 if(!force&&sig===lastMsgsHash&&LOG.dataset.wa===wa)return;   // U2: skip identical rebuild
 lastMsgsHash=sig;LOG.dataset.wa=wa;
 const atBottom=LOG.scrollHeight-LOG.scrollTop-LOG.clientHeight<120;
 const prevWa=LOG.dataset.prevWa,prevTop=LOG.scrollTop,prevH=LOG.scrollHeight;
 LOG.innerHTML='';
 if(d.length>=500&&!oldestId&&!document.getElementById('olderBtn')){{
  const ob=document.createElement('button');ob.id='olderBtn';ob.className='loadOlder';
  ob.textContent='↑ تحميل الأقدم';ob.onclick=()=>loadOlder(d[0].id);LOG.appendChild(ob);}}
 else if(oldestId&&d.length<200){{const ob=document.getElementById('olderBtn');if(ob)ob.remove()}}
 if(d.length)oldestId=d[0].id;
 if(!d.length){{LOG.innerHTML='<div class="empty">لا رسائل في هذه المحادثة</div>';return}}
 let lastDay='';const unread=[];
 d.forEach(m=>{{
  const day=(m.created_at||'').slice(0,10);
  if(day&&day!==lastDay){{lastDay=day;
   const dd=document.createElement('div');dd.className='day';dd.textContent=day;LOG.appendChild(dd)}}
  const w=document.createElement('div');w.className='msg '+m.direction;
  w.style.position='relative';
  w.dataset.pk=(m.id||'');w.dataset.wmid=(m.wa_message_id||'');
  const mh=mediaHtml(m);
  if(mh){{const mw=document.createElement('div');mw.innerHTML=mh;w.appendChild(mw.firstChild||mw)}}
  const cap=(m.caption||'');
  if(cap){{const t=document.createElement('span');t.textContent=m.caption;w.appendChild(t)}}
  else if(!mh){{w.appendChild(document.createTextNode(m.body??''))}}
  const acts=document.createElement('div');
  if(m.direction==='in'){{
   acts.className='reactbar';
   ['👍','❤️','😂','😮','😢','🙏'].forEach(em=>{{
    const b=document.createElement('button');b.textContent=em;b.type='button';
    b.onclick=(ev)=>{{ev.stopPropagation();doReact(m.wa_message_id,em)}};
    acts.appendChild(b);}});
   const rep=document.createElement('button');rep.textContent='↩';rep.title='رد';
   rep.onclick=(ev)=>{{ev.stopPropagation();w.classList.remove('open');startReply(m)}};
   acts.appendChild(rep);
   const qb=document.createElement('button');qb.type='button';qb.className='qreact';
   qb.textContent='😊';qb.title='تفاعل';
   qb.onclick=(ev)=>{{ev.stopPropagation();w.classList.remove('open');openEp('react',m.wa_message_id)}};
   w.appendChild(qb);
  }} else {{
   acts.className='acts';
   const del=document.createElement('button');del.textContent='🗑';del.title='إخفاء لدي فقط';
   del.onclick=(ev)=>{{ev.stopPropagation();hideMsg(+m.id)}};
   acts.appendChild(del);}}
  w.appendChild(acts);
  w.onclick=(ev)=>{{
   document.querySelectorAll('.msg.open').forEach(x=>{{if(x!==w)x.classList.remove('open')}});
   w.classList.toggle('open');
  }};
  if(m.quoted){{
   const qb=document.createElement('div');qb.className='quotebox';
   qb.textContent='↩ '+m.quoted;
   w.insertBefore(qb,w.firstChild);}}
  const meta=document.createElement('div');meta.className='meta';
  meta.innerHTML='<span>'+esc((m.created_at||'').slice(11,16))+'</span>'+ticks(m);
  w.appendChild(meta);LOG.appendChild(w);
  if(m.reaction){{
   const rx=document.createElement('span');rx.className='rx';rx.textContent=m.reaction;
   w.appendChild(rx);}}
  if(m.direction==='in'&&m.wa_message_id&&m.status!=='read')unread.push(m.wa_message_id);
 }});
 // U2: snap only when already at bottom (or switching chats) — never yank a reader
 if(atBottom||prevWa!==wa){{LOG.scrollTop=LOG.scrollHeight}}
 else{{LOG.scrollTop=prevTop+(LOG.scrollHeight-prevH)}}
 LOG.dataset.prevWa=wa;
 if(unread.length)fetch('{base}/api/read',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{message_ids:unread}})}}).then(()=>loadMsgs()).catch(()=>{{}});}}
async function loadOlder(beforeId){{
 if(!current)return;
 const tok=++msgToken,wa=current;
 const r=await fetch('{base}/api/messages?wa_id='+encodeURIComponent(wa)+'&before_id='+beforeId);
 if(r.status===403)location.reload();
 if(tok!==msgToken||wa!==current)return;
 if(!r.ok){{showToast('✗ فشل تحميل الأقدم');return}}
 const d=await r.json();
 const ob=document.getElementById('olderBtn');
 if(!d.length){{if(ob)ob.remove();showToast('بداية المحادثة');return}}
 oldestId=d[0].id;
 const anchor=LOG.scrollHeight;
 d.forEach(m=>{{
  const w=document.createElement('div');w.className='msg '+m.direction;
  w.style.position='relative';
  w.appendChild(document.createTextNode(m.body??''));
  if(m.quoted){{const qb=document.createElement('div');qb.className='quotebox';
   qb.textContent='↩ '+m.quoted;w.appendChild(qb)}}
  if(ob){{LOG.insertBefore(w,ob)}}else{{LOG.appendChild(w)}}
 }});
 LOG.scrollTop=LOG.scrollHeight-anchor;   // keep viewport anchored
 if(d.length<200&&ob)ob.remove();         // exhausted history
}}
async function sendPayload(payload){{
 const SEND=document.getElementById('send');SEND.disabled=true;
 showToast('⏳ جارٍ الإرسال…');
 try{{
  const r=await fetch('{base}/api/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify(payload)}});
  if(r.status===403)location.reload();
  if(!r.ok)throw new Error('http '+r.status);
  hideToast();
  loadMsgs(true);loadLeads();
  return true;
 }}catch(e){{showToast('✗ فشل الإرسال — لم تُفقد نصّك، حاول مجدداً');return false}}
 finally{{SEND.disabled=false}}}}
const EP_CATS=[
 ['😀','وجوه','😀 😃 😄 😁 😆 😅 😂 🤣 🥲 ☺️ 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😝 😜 🤪 🤨 🧐 🤓 😎 🥸 🤩 🥳 😏 😒 😞 😔 😟 😕 🙁 ☹️ 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😨 😰 😥 😓 🫡 🤗 🫢 🤭 🫣 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕'],
 ['👍','إشارات','👍 👎 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👋 🤚 🖐️ ✋ 🖖 👏 🙌 🤲 🤝 🙏 ✍️ 💅 🤳 💪 🦾 🦵 🦶 👂 👃 🧠 🫀 👀 👁️ 👅 👄 💋 🩸'],
 ['❤️','قلوب','❤️ 🩷 🧡 💛 💚 💙 🩵 💜 🖤 🩶 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 ✨ ⭐ 🌟 💫 ⚡ 🔥 💥 💯 🎉 🎊 🎈 🎁 🏆 🥇 🎯'],
 ['🐶','حيوانات','🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐻‍❄️ 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🙈 🙉 🙊 🐔 🐧 🐦 🐤 🦆 🦅 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🐛 🦋 🐌 🐞 🐜 🕷️ 🦂 🐢 🐍 🦎 🐙 🦑 🦐 🦞 🦀 🐡 🐠 🐟 🐬 🐳 🐋 🦈'],
 ['🍕','طعام','🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍈 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🍆 🥑 🥦 🥬 🌽 🥕 🧄 🧅 🥔 🍠 🥐 🍞 🥖 🥨 🧀 🥚 🍳 🥞 🧇 🥓 🍗 🍖 🌭 🍔 🍟 🍕 🥪 🌮 🌯 🥗 🍝 🍜 🍲 🍛 🍣 🍱 🍤 🍙 🍚 🥟 🍦 🍩 🍪 🎂 🍰 🧁 🍫 🍬 🍭 ☕ 🍵 🧃 🥤 🧋'],
 ['⚽','أنشطة','⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🎱 🏓 🏸 🥅 🏒 🏑 🏏 ⛳ 🏹 🎣 🥊 🥋 🎽 🛹 🛼 ⛸️ 🎿 ⛷️ 🏂 🏋️ 🤼 🤸 ⛹️ 🤺 🤾 🏌️ 🏇 🧘 🏄 🏊 🤽 🚣 🧗 🚴 🚵 🎮 🕹️ 🎲 ♟️ 🧩 🎯 🎳 🎪 🎭 🎨 🎬 🎤 🎧 🎸 🎹 🥁 🎷 🎺 🎻'],
 ['✈️','سفر','🚗 🚕 🚙 🚌 🚎 🏎️ 🚓 🚑 🚒 🚐 🛻 🚚 🚛 🚜 🛵 🏍️ 🚲 🛴 ✈️ 🛫 🛬 🚀 🛸 🚁 ⛵ 🚢 🚤 🛥️ ⛴️ 🗺️ 🧭 🏝️ 🏔️ ⛰️ 🌋 🏕️ 🏖️ 🏜️ 🎡 🎢 🎠 ⛲ ⛱️ 🌅 🌄 🌇 🌃 🗽 🗼 🕌 ⛩️ 🏰 🏯'],
 ['🔧','أشياء','⌚ 📱 💻 ⌨️ 🖥️ 🖨️ 💾 💿 📷 📹 🎥 📞 ☎️ 📺 📻 🎙️ ⏰ ⌛ 💡 🔋 🔌 📚 📖 📝 ✏️ 📌 📎 🔒 🔑 🔨 🛠️ ⚙️ 🧲 💊 💉 🩹 🧬 🔬 🔭 🧸 💎 🛒 🎈 ✉️ 📦 🚪 🪑 🛏️ 🚿 🧴 🧹 🕯️ 💰 💳'],
];
let epMode=null,epWmid=null,epCat=0;
function renderEpTabs(){{
 const t=document.getElementById('epTabs');t.innerHTML='';
 EP_CATS.forEach((c,i)=>{{
  const b=document.createElement('button');b.textContent=c[0];b.title=c[1];
  b.className=i===epCat?'on':'';b.onclick=()=>{{epCat=i;renderEpTabs();renderEpGrid()}};
  t.appendChild(b);}});}}
function renderEpGrid(){{
 const g=document.getElementById('epGrid');g.innerHTML='';
 EP_CATS[epCat][2].split(' ').forEach(em=>{{
  const b=document.createElement('button');b.textContent=em;b.type='button';
  b.onclick=()=>epPick(em);g.appendChild(b);}});
 g.scrollTop=0;}}
function openEp(mode,wmid){{
 epMode=mode;epWmid=wmid||null;
 document.getElementById('emojiPanel').classList.add('open');
 renderEpTabs();renderEpGrid();}}
function closeEp(){{
 document.getElementById('emojiPanel').classList.remove('open');epMode=null;epWmid=null;}}
function epPick(em){{
 if(epMode==='composer'){{
  const s=TEXT.selectionStart??TEXT.value.length,e=TEXT.selectionEnd??s;
  TEXT.value=TEXT.value.slice(0,s)+em+TEXT.value.slice(e);
  TEXT.selectionStart=TEXT.selectionEnd=s+em.length;TEXT.focus();}}
 else if(epMode==='react'&&epWmid)doReact(epWmid,em);
 closeEp();}}
document.getElementById('emojibtn').onclick=(ev)=>{{
 ev.stopPropagation();
 document.getElementById('emojiPanel').classList.contains('open')?closeEp():openEp('composer');}};
document.addEventListener('click',e=>{{
 const pnl=document.getElementById('emojiPanel');
 if(!pnl.classList.contains('open'))return;
 if(pnl.contains(e.target))return;
 if(e.target.id==='emojibtn')return;
 if(e.target.closest&&e.target.closest('.qreact'))return;
 closeEp();}});
async function doReact(wmid,emoji){{
 if(!wmid)return;
 await fetch('{base}/api/react',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{wa_id:current,message_id:wmid,emoji}})}});
 loadMsgs();}}
async function hideMsg(pk){{
 await fetch('{base}/api/hide',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{id:pk}})}});
 loadMsgs();}}
function startReply(m){{
 pendingReply={{message_id:m.wa_message_id,snippet:(m.caption||m.body||'').slice(0,80)}};
 const rb=document.getElementById('replybar');
 rb.querySelector('.q').textContent='↩ رد على: '+(pendingReply.snippet||'رسالة');
 rb.style.display='flex';TEXT.focus();}}
document.querySelector('#replybar button').onclick=()=>{{
 pendingReply=null;document.getElementById('replybar').style.display='none';}};
document.getElementById('composer').addEventListener('submit',async e=>{{
 e.preventDefault();
 if(pendingMedia){{
  const p={{wa_id:current,text:TEXT.value.trim(),
   media:{{kind:pendingMedia.kind,filename:pendingMedia.filename,mime:pendingMedia.mime,
          data_base64:pendingMedia.data_base64}}}};
  if(pendingReply){{p.reply_to=pendingReply.message_id}}
 const ok=await sendPayload(p);
 if(ok){{TEXT.value='';clearPending();
  pendingReply=null;document.getElementById('replybar').style.display='none'}}
 return}}
 if(!current||!TEXT.value.trim())return;
 const t=TEXT.value.trim();
 const pt={{wa_id:current,text:t}};
 if(pendingReply){{pt.reply_to=pendingReply.message_id}}
 const ok=await sendPayload(pt);
 if(ok){{TEXT.value='';
  pendingReply=null;document.getElementById('replybar').style.display='none'}}}});
/* attachments */
document.getElementById('attach').onclick=()=>FILE.click();
FILE.addEventListener('change',()=>{{
 const f=FILE.files[0];if(!f)return;
 if(f.size>30*1024*1024){{alert('الحد الأقصى 30MB');FILE.value='';return}}
 const kind=f.type.startsWith('image/')?'image':f.type.startsWith('audio/')?'audio':
            f.type.startsWith('video/')?'video':'document';
 const rd=new FileReader();
 rd.onload=()=>{{pendingMedia={{kind,filename:f.name,mime:f.type||'application/octet-stream',
   data_base64:rd.result.split(',')[1]}};
  document.getElementById('preview-info').textContent='📎 '+f.name+' ('+fmtSize(f.size)+')';
  PREVIEW.hidden=false;}};
 rd.readAsDataURL(f);FILE.value='';}});
function clearPending(){{pendingMedia=null;PREVIEW.hidden=true}}
document.getElementById('preview-cancel').onclick=clearPending;
/* voice recording */
const MIC=document.getElementById('mic');
MIC.onclick=async()=>{{
 if(recorder&&recorder.state==='recording'){{recorder.stop();return}}
 try{{
  const stream=await navigator.mediaDevices.getUserMedia({{audio:true}});
  recorder=new MediaRecorder(stream);
  chunks=[];
  recorder.ondataavailable=e=>chunks.push(e.data);
  recorder.onstop=()=>{{
   stream.getTracks().forEach(t=>t.stop());
   MIC.classList.remove('recording');MIC.textContent='🎤';clearInterval(MIC._timer);
   const blob=new Blob(chunks,{{type:recorder.mimeType||'audio/webm'}});
   const rd=new FileReader();
   rd.onload=()=>{{
    pendingMedia={{kind:'audio',filename:'voice-note.'+(blob.type.includes('mp4')?'mp4':'webm'),
     mime:blob.type,data_base64:rd.result.split(',')[1]}};
    document.getElementById('preview-info').textContent='🎙️ تسجيل صوتي ('+fmtSize(blob.size)+')';
    PREVIEW.hidden=false;}};
   rd.readAsDataURL(blob);}};
  recorder.start();MIC.classList.add('recording');MIC.textContent='⏹';
  let secs=0;MIC._timer=setInterval(()=>{{secs++;MIC.textContent='⏹ '+secs+'s'}},1000);
 }}catch(err){{alert('تعذر الوصول للميكروفون: '+err.message)}}}};
timer=setInterval(()=>{{loadLeads();if(current)loadMsgs();}},6000);
loadLeads();
</script></body></html>"""


def render_inbox_page(base_path: str, logout_path: str) -> str:
    return _INBOX_PAGE.format(base=html.escape(base_path), logout=html.escape(logout_path))
