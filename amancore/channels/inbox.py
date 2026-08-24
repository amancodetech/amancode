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

    def is_locked(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        with self._lock:
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
}


def security_headers() -> dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    headers["X-Robots-Tag"] = "noindex, nofollow"
    return headers


_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow"><title>·</title>
<style>
body{{font-family:system-ui,sans-serif;background:#101c30;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
form{{background:#f7f3ea;padding:2rem;border-radius:12px;width:min(320px,90vw);box-shadow:0 10px 40px rgba(0,0,0,.4)}}
h1{{font-size:1.1rem;margin:0 0 1rem;color:#101c30}}
input{{width:100%;padding:.6rem;border:1px solid #c9a86a;border-radius:6px;margin-bottom:.8rem;box-sizing:border-box;font-size:1rem}}
button{{width:100%;padding:.6rem;background:#101c30;color:#c9a86a;border:0;border-radius:6px;font-size:1rem;cursor:pointer}}
.err{{color:#b00020;font-size:.85rem;margin-bottom:.6rem}}
</style></head><body><form method="post" action="{action}">
<h1>🔒 AmanCore Inbox</h1>
{error}
<input type="password" name="password" placeholder="كلمة المرور" autofocus required autocomplete="current-password">
<button type="submit">دخول</button></form></body></html>"""


def render_login_page(action_path: str, error: str = "") -> str:
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return _LOGIN_PAGE.format(action=html.escape(action_path), error=err_html)


_INBOX_PAGE = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow"><title>AmanCore Inbox</title>
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
.tick{{color:#53bdeb;font-weight:bold}}
.day{{align-self:center;background:#182229;color:#8696a0;font-size:.72rem;padding:.25rem .8rem;border-radius:8px;margin-bottom:.5rem}}
.empty{{color:#8696a0;text-align:center;margin-top:3rem;font-size:.9rem}}
#composer{{display:flex;gap:.5rem;padding:.6rem .8rem;background:#202c33;align-items:center}}
#text{{flex:1;padding:.7rem 1rem;border:0;border-radius:10px;background:#2a3942;color:#e9edef;font-size:1rem;outline:none}}
#send{{width:44px;height:44px;border-radius:50%;border:0;background:#00a884;color:#fff;font-size:1.2rem;cursor:pointer;flex-shrink:0}}
#send:hover{{background:#06cf9c}}
@media(max-width:700px){{aside{{width:100%;display:none}} aside.open{{display:flex}}
 body.chatting aside{{display:none}} main{{display:none}} body.chatting main{{display:flex}}}}
::-webkit-scrollbar{{width:6px}} ::-webkit-scrollbar-thumb{{background:#374248;border-radius:3px}}
</style></head><body>
<aside id="leadsPanel"><div class="panel-head">💬 المحادثات</div><div id="leads"><div class="empty">لا محادثات بعد</div></div></aside>
<main id="chatArea">
<header><span id="who">AmanCore Inbox</span><form method="post" action="{logout}"><button>خروج ⏻</button></form></header>
<div id="log"><div class="empty">اختر محادثة من القائمة لعرض الرسائل</div></div>
<form id="composer"><input id="text" placeholder="اكتب رسالة…" autocomplete="off"><button id="send">➤</button></form>
</main>
<script>
const LEADS=document.getElementById('leads'),LOG=document.getElementById('log'),
WHO=document.getElementById('who'),TEXT=document.getElementById('text');
let current=null,timer=null;
function esc(s){{const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}}
async function loadLeads(){{
 const r=await fetch('{base}/api/leads');if(r.status===403)location.reload();
 const d=await r.json();
 if(!d.length){{LEADS.innerHTML='<div class="empty">لا محادثات بعد<br>ستظهر هنا رسائل العملاء تلقائيًا</div>';return}}
 LEADS.innerHTML='';
 d.forEach(l=>{{
  const el=document.createElement('div');el.className='lead'+(l.wa_id===current?' sel':'');
  const initial=esc((l.name||l.wa_id||'?').trim()[0]||'?').toUpperCase();
  const human=(l.mode==='HUMAN_ACTIVE'||l.mode==='HUMAN_REQUESTED');
  el.innerHTML='<div class="avatar">'+initial+'</div>'+
   '<div class="lead-info"><div class="lead-name">'+esc(l.name||'عميل')+
   '<span class="mode-chip'+(human?' human':'')+'">'+(human?'👤 بشري':'🤖 AI')+'</span></div>'+
   '<div class="lead-sub">'+esc(l.wa_id)+(l.last_at?' · '+esc(l.last_at.slice(5,16)):'')+'</div></div>';
  el.onclick=()=>{{
   current=l.wa_id;WHO.textContent=(l.name||'')+' · '+l.wa_id;
   document.querySelectorAll('.lead').forEach(x=>x.classList.remove('sel'));el.classList.add('sel');
   document.body.classList.add('chatting');loadMsgs();TEXT.focus()}};
  LEADS.appendChild(el);
 }});}}
async function loadMsgs(){{
 if(!current)return;
 const r=await fetch('{base}/api/messages?wa_id='+encodeURIComponent(current));
 if(r.status===403)location.reload();
 const d=await r.json();LOG.innerHTML='';
 if(!d.length){{LOG.innerHTML='<div class="empty">لا رسائل في هذه المحادثة</div>';return}}
 let lastDay='';
 d.forEach(m=>{{
  const day=(m.created_at||'').slice(0,10);
  if(day&&day!==lastDay){{lastDay=day;
   const dd=document.createElement('div');dd.className='day';dd.textContent=day;LOG.appendChild(dd)}}
  const w=document.createElement('div');w.className='msg '+m.direction;
  w.appendChild(document.createTextNode(m.body));
  const meta=document.createElement('div');meta.className='meta';
  meta.innerHTML='<span>'+esc((m.created_at||'').slice(11,16))+'</span>'+
   (m.direction==='out'
     ?(m.status==='sent'?'<span class="tick">✓✓</span>'
       :m.status==='failed'?'<span style="color:#f15c6d">✗ '+esc(m.status)+'</span>'
       :'<span>🕐</span>'):'');
  w.appendChild(meta);LOG.appendChild(w);
 }});
 LOG.scrollTop=LOG.scrollHeight;}}
document.getElementById('composer').addEventListener('submit',async e=>{{
 e.preventDefault();if(!current||!TEXT.value.trim())return;
 await fetch('{base}/api/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{wa_id:current,text:TEXT.value.trim()}})}});
 TEXT.value='';loadMsgs();}});
timer=setInterval(()=>{{loadLeads();if(current)loadMsgs();}},6000);
loadLeads();
</script></body></html>"""


def render_inbox_page(base_path: str, logout_path: str) -> str:
    return _INBOX_PAGE.format(base=html.escape(base_path), logout=html.escape(logout_path))
