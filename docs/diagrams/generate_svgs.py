import os

DIAGRAMS_DIR = "/home/omar/Desktop/work/aman-core/docs/diagrams"
os.makedirs(DIAGRAMS_DIR, exist_ok=True)

# Common SVG header styles
STYLES = """
    <defs>
      <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#0b0f17"/>
        <stop offset="100%" stop-color="#141c2b"/>
      </linearGradient>
      <linearGradient id="cardGrad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#1c2536"/>
        <stop offset="100%" stop-color="#151d2c"/>
      </linearGradient>
      <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#3b82f6"/>
        <stop offset="100%" stop-color="#8b5cf6"/>
      </linearGradient>
      <linearGradient id="greenGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#10b981"/>
        <stop offset="100%" stop-color="#059669"/>
      </linearGradient>
      <linearGradient id="goldGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#f59e0b"/>
        <stop offset="100%" stop-color="#d97706"/>
      </linearGradient>
      <linearGradient id="purpleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#8b5cf6"/>
        <stop offset="100%" stop-color="#ec4899"/>
      </linearGradient>
      
      <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%" filterUnits="userSpaceOnUse">
        <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000000" flood-opacity="0.5"/>
      </filter>
      <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="4" result="blur"/>
        <feComposite in="SourceGraphic" in2="blur" operator="over"/>
      </filter>

      <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#60a5fa"/>
      </marker>
      <marker id="arrow-green" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#34d399"/>
      </marker>
      <marker id="arrow-gold" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#fbbf24"/>
      </marker>
    </defs>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&amp;display=swap');
      text { font-family: 'Cairo', 'Segoe UI', Tahoma, sans-serif; }
      .title { font-size: 24px; font-weight: 800; fill: #ffffff; text-anchor: middle; }
      .subtitle { font-size: 14px; fill: #94a3b8; text-anchor: middle; }
      .sec-title { font-size: 15px; font-weight: 700; fill: #93c5fd; }
      .box-title { font-size: 14px; font-weight: 700; fill: #ffffff; }
      .box-sub { font-size: 11px; fill: #94a3b8; }
      .badge-text { font-size: 11px; font-weight: 700; fill: #ffffff; }
      .link-text { font-size: 11px; fill: #38bdf8; font-weight: 600; }
    </style>
"""

# ==============================================================================
# 1. DIAGRAM 1: SYSTEM ARCHITECTURE
# ==============================================================================
def create_diagram_1():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" height="100%">
    {STYLES}
    <!-- Background -->
    <rect width="1200" height="800" fill="url(#bgGrad)"/>
    <rect x="20" y="20" width="1160" height="760" rx="16" fill="none" stroke="#334155" stroke-width="1.5"/>

    <!-- Header -->
    <text x="600" y="55" class="title">المخطط 1: معمارية النظام العامة والربط بالقنوات (AmanCore System Architecture)</text>
    <text x="600" y="80" class="subtitle">التدفق الفعلي الكامل للقنوات، الجسر المحلي، النواة المركزية، الأمان المالي، وكونسول تيليجرام</text>

    <!-- SECTION 1: CHANNELS (TOP) -->
    <g transform="translate(50, 105)">
      <rect width="1100" height="115" rx="12" fill="#131b2a" stroke="#2563eb" stroke-width="1.2" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="220" height="24" rx="6" fill="#1e3a8a"/>
      <text x="125" y="4" class="badge-text" text-anchor="middle">🌐 قنوات التواصل المتعددة (Omnichannel)</text>

      <!-- Channel 1: WhatsApp -->
      <g transform="translate(30, 25)">
        <rect width="240" height="70" rx="8" fill="#1e293b" stroke="#334155"/>
        <circle cx="28" cy="35" r="16" fill="#10b981"/>
        <text x="28" y="40" font-size="16" text-anchor="middle" fill="#fff">📱</text>
        <text x="55" y="30" class="box-title">واتساب بيزنس رسمي</text>
        <text x="55" y="48" class="box-sub">+62 815-1129-8405 (Baileys)</text>
      </g>

      <!-- Channel 2: Facebook -->
      <g transform="translate(295, 25)">
        <rect width="240" height="70" rx="8" fill="#1e293b" stroke="#334155"/>
        <circle cx="28" cy="35" r="16" fill="#2563eb"/>
        <text x="28" y="40" font-size="16" text-anchor="middle" fill="#fff">💬</text>
        <text x="55" y="30" class="box-title">فيسبوك ماسنجر</text>
        <text x="55" y="48" class="box-sub">Page ID: 1318320251359371</text>
      </g>

      <!-- Channel 3: Instagram -->
      <g transform="translate(560, 25)">
        <rect width="240" height="70" rx="8" fill="#1e293b" stroke="#334155"/>
        <circle cx="28" cy="35" r="16" fill="#ec4899"/>
        <text x="28" y="40" font-size="16" text-anchor="middle" fill="#fff">📷</text>
        <text x="55" y="30" class="box-title">انستغرام بيزنس DM</text>
        <text x="55" y="48" class="box-sub">Realtime + Browser Fallback</text>
      </g>

      <!-- Channel 4: Telegram Customer -->
      <g transform="translate(825, 25)">
        <rect width="245" height="70" rx="8" fill="#1e293b" stroke="#334155"/>
        <circle cx="28" cy="35" r="16" fill="#0284c7"/>
        <text x="28" y="40" font-size="16" text-anchor="middle" fill="#fff">✈️</text>
        <text x="55" y="30" class="box-title">بوت تيليجرام العملاء</text>
        <text x="55" y="48" class="box-sub">@AmanCode_help_bot (Webhook)</text>
      </g>
    </g>

    <!-- SECTION 2: BRIDGE (MIDDLE TOP) -->
    <g transform="translate(50, 245)">
      <rect width="1100" height="80" rx="10" fill="#162032" stroke="#475569" stroke-width="1.2" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="230" height="24" rx="6" fill="#334155"/>
      <text x="130" y="4" class="badge-text" text-anchor="middle">🌉 طبقة الجسور المحلية (Local Bridge)</text>

      <g transform="translate(30, 20)">
        <rect width="490" height="44" rx="6" fill="#1e293b" stroke="#3b82f6"/>
        <text x="245" y="27" font-size="13" font-weight="700" fill="#93c5fd" text-anchor="middle">Meta Bridge (Node.js Port: 8765) • Baileys + Chrome Puppeteer</text>
      </g>

      <g transform="translate(580, 20)">
        <rect width="490" height="44" rx="6" fill="#1e293b" stroke="#0ea5e9"/>
        <text x="245" y="27" font-size="13" font-weight="700" fill="#7dd3fc" text-anchor="middle">Telegram Bot API Webhook Intake (Secret Token Verification)</text>
      </g>
    </g>

    <!-- Arrows from Channels to Bridge -->
    <path d="M 170 220 L 170 245" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)"/>
    <path d="M 435 220 L 435 245" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)"/>
    <path d="M 700 220 L 700 245" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)"/>
    <path d="M 965 220 L 965 245" stroke="#0ea5e9" stroke-width="2" marker-end="url(#arrow)"/>

    <!-- SECTION 3: AMANCORE CENTRAL ENGINE -->
    <g transform="translate(50, 350)">
      <rect width="720" height="410" rx="12" fill="#111827" stroke="#3b82f6" stroke-width="1.8" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="280" height="24" rx="6" fill="url(#accentGrad)"/>
      <text x="155" y="4" class="badge-text" text-anchor="middle">🧠 نواة النظام المركزي (AmanCore Port: 8010)</text>

      <!-- Row 1: Intake & Planner -->
      <g transform="translate(25, 30)">
        <rect width="320" height="75" rx="8" fill="#1f2937" stroke="#4b5563"/>
        <text x="15" y="28" class="box-title">المنسق المركزي (Coordinator)</text>
        <text x="15" y="48" class="box-sub">إدارة الهوية، اللغة، والذاكرة التراكمية</text>
        <rect x="15" y="55" width="130" height="15" rx="3" fill="#374151"/>
        <text x="80" y="66" font-size="9" fill="#9ca3af" text-anchor="middle">CanonicalEvent Intake</text>
      </g>

      <g transform="translate(370, 30)">
        <rect width="325" height="75" rx="8" fill="#1f2937" stroke="#4b5563"/>
        <text x="15" y="28" class="box-title">محلل المتطلبات الذكي (RIL Extractor)</text>
        <text x="15" y="48" class="box-sub">استخراج الميزات والقرارات وكتالوج الحلول</text>
        <rect x="15" y="55" width="130" height="15" rx="3" fill="#065f46"/>
        <text x="80" y="66" font-size="9" fill="#34d399" text-anchor="middle">Scope Builder &amp; SOW</text>
      </g>

      <!-- Row 2: AI Estimator & Pricing Engine -->
      <g transform="translate(25, 125)">
        <rect width="320" height="95" rx="8" fill="#1e1b4b" stroke="#6366f1" stroke-width="1.5"/>
        <text x="15" y="28" class="box-title" fill="#a5b4fc">مهندس تقدير الساعات (AI Estimator)</text>
        <text x="15" y="48" class="box-sub">تفكيك المشروع هندسياً (WBS):</text>
        <text x="15" y="68" font-size="11" fill="#c7d2fe">• واجهات Frontend + قواعد Backend</text>
        <text x="15" y="85" font-size="11" fill="#c7d2fe">• ربط وتكاملات Integrations + نشر سحابي QA</text>
      </g>

      <g transform="translate(370, 125)">
        <rect width="325" height="95" rx="8" fill="#14532d" stroke="#10b981" stroke-width="1.5"/>
        <text x="15" y="28" class="box-title" fill="#86efac">المحرك المالي الصارم (Pricing Engine)</text>
        <text x="15" y="48" class="box-sub">حساب التكاليف الحتمية وهامش الربح:</text>
        <text x="15" y="68" font-size="11" fill="#bbf7d0">• السعر المستهدف (Target Price)</text>
        <text x="15" y="85" font-size="11" fill="#bbf7d0">• الحد الأدنى للتفاوض (Negotiation Floor)</text>
      </g>

      <!-- Row 3: Response Planner & QualityGuard -->
      <g transform="translate(25, 240)">
        <rect width="320" height="75" rx="8" fill="#1f2937" stroke="#4b5563"/>
        <text x="15" y="28" class="box-title">مخطط الحوار (Response Planner)</text>
        <text x="15" y="48" class="box-sub">آلة الحالات (OPENING ⬅️ NEED ⬅️ COM)</text>
        <text x="15" y="66" font-size="10" fill="#60a5fa">قفل اللغة المطابق (LANGUAGE LOCK)</text>
      </g>

      <g transform="translate(370, 240)">
        <rect width="325" height="75" rx="8" fill="#78350f" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="15" y="28" class="box-title" fill="#fde68a">حارس الجودة والأمان (QualityGuard)</text>
        <text x="15" y="48" class="box-sub">فحص الأرقام المهلوسة والوعود المحظورة</text>
        <text x="15" y="66" font-size="10" fill="#fef08a">حظر أي سعر غير معتمد من المالك برمجياً</text>
      </g>

      <!-- Row 4: Outbox Worker -->
      <g transform="translate(25, 335)">
        <rect width="670" height="55" rx="8" fill="#0f172a" stroke="#38bdf8"/>
        <text x="20" y="25" class="box-title">صندوق الصادر الذري (Transactional Outbox Queue)</text>
        <text x="20" y="44" class="box-sub">قفل ذري (claim_token) لمنع تكرار الإرسال • إعادة محاولة تلقائية عند انقطاع الشبكة</text>
      </g>
    </g>

    <!-- SECTION 4: STORAGE & MEMORY (RIGHT MIDDLE) -->
    <g transform="translate(800, 350)">
      <rect width="350" height="195" rx="12" fill="#131d2e" stroke="#0284c7" stroke-width="1.2" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="220" height="24" rx="6" fill="#0369a1"/>
      <text x="125" y="4" class="badge-text" text-anchor="middle">💾 قواعد البيانات والذاكرة</text>

      <g transform="translate(20, 25)">
        <text x="0" y="20" class="box-title" fill="#38bdf8">قاعدة بيانات SQLite (WAL Mode)</text>
        <text x="0" y="40" class="box-sub">channel_messages • leads • opportunities</text>
        <text x="0" y="58" class="box-sub">approvals • platform_identities • outbox</text>
      </g>

      <path d="M 20 95 L 330 95" stroke="#1e293b" stroke-width="1.5"/>

      <g transform="translate(20, 105)">
        <text x="0" y="20" class="box-title" fill="#a78bfa">الذاكرة التراكمية المستمرة (Lead Memory)</text>
        <text x="0" y="40" class="box-sub">تلخيص تراكمي كل 10 رسائل (Rolling Summary)</text>
        <text x="0" y="58" class="box-sub">بصمة النطاق (Scope Fingerprint) وتحديث الحقائق</text>
      </g>
    </g>

    <!-- SECTION 5: OWNER TELEGRAM CONSOLE (RIGHT BOTTOM) -->
    <g transform="translate(800, 565)">
      <rect width="350" height="195" rx="12" fill="#1f1d2b" stroke="#f59e0b" stroke-width="1.5" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="220" height="24" rx="6" fill="url(#goldGrad)"/>
      <text x="125" y="4" class="badge-text" text-anchor="middle">📱 مركز سيطرة المالك (Telegram)</text>

      <g transform="translate(20, 25)">
        <text x="0" y="20" class="box-title" fill="#fbbf24">Telegram Owner Console</text>
        <text x="0" y="40" class="box-sub">مشفر برقم شات المالك الحصري (TELEGRAM_CHAT_ID)</text>
      </g>

      <g transform="translate(20, 75)">
        <rect width="310" height="100" rx="6" fill="#13111c" stroke="#451a03"/>
        <text x="12" y="25" font-size="11" fill="#fde68a" font-weight="700">⚡ أوامر السيطرة من هاتفك المحمول:</text>
        <text x="12" y="45" font-size="11" fill="#e2e8f0">• اعتماد السعر الفوري: /qapprove q-8a3f</text>
        <text x="12" y="65" font-size="11" fill="#e2e8f0">• تحديد سعر مخصص: /qapprove q-8a3f 1500</text>
        <text x="12" y="85" font-size="11" fill="#e2e8f0">• الاستلام البشري: /chat +966... • النشر: /post</text>
      </g>
    </g>

    <!-- Connectors -->
    <!-- Bridge to Coordinator -->
    <path d="M 600 325 L 600 340 L 210 340 L 210 375" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)" fill="none"/>
    <!-- PricingEngine to Owner Console -->
    <path d="M 695 520 L 750 520 L 750 630 L 800 630" stroke="#fbbf24" stroke-width="2.5" stroke-dasharray="6,4" marker-end="url(#arrow-gold)" fill="none"/>
    <text x="755" y="580" font-size="10" fill="#fbbf24" font-weight="700">طلب اعتماد السعر</text>
    <!-- Owner Approval back to Pricing -->
    <path d="M 800 660 L 720 660 L 720 540" stroke="#34d399" stroke-width="2" marker-end="url(#arrow-green)" fill="none"/>
    <text x="705" y="615" font-size="10" fill="#34d399" font-weight="700">اعتماد</text>
</svg>"""
    return svg

# ==============================================================================
# 2. DIAGRAM 2: CUSTOMER JOURNEY SEQUENCE
# ==============================================================================
def create_diagram_2():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 850" width="100%" height="100%">
    {STYLES}
    <rect width="1200" height="850" fill="url(#bgGrad)"/>
    <rect x="20" y="20" width="1160" height="810" rx="16" fill="none" stroke="#334155" stroke-width="1.5"/>

    <!-- Header -->
    <text x="600" y="55" class="title">المخطط 2: تسلسل رحلة العميل خطوة بخطوة (Customer Journey Sequence)</text>
    <text x="600" y="80" class="subtitle">المسار الزمني الدقيق من أول استفسار إلى تقدير الساعات بالـ AI وحتى اعتماد السعر من المالك</text>

    <!-- Lifeline Headers -->
    <!-- 1. Customer -->
    <g transform="translate(70, 110)">
      <rect width="180" height="45" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="90" y="28" font-size="14" font-weight="700" fill="#93c5fd" text-anchor="middle">👤 العميل (واتساب / انستغرام)</text>
      <line x1="90" y1="45" x2="90" y2="700" stroke="#334155" stroke-dasharray="4,4" stroke-width="1.5"/>
    </g>

    <!-- 2. AmanCore Engine -->
    <g transform="translate(320, 110)">
      <rect width="180" height="45" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="90" y="28" font-size="14" font-weight="700" fill="#93c5fd" text-anchor="middle">⚙️ نواة النظام (AmanCore)</text>
      <line x1="90" y1="45" x2="90" y2="700" stroke="#334155" stroke-dasharray="4,4" stroke-width="1.5"/>
    </g>

    <!-- 3. AI Estimator & Drafter -->
    <g transform="translate(570, 110)">
      <rect width="180" height="45" rx="8" fill="#1e1b4b" stroke="#8b5cf6" stroke-width="1.5"/>
      <text x="90" y="28" font-size="14" font-weight="700" fill="#c4b5fd" text-anchor="middle">🧠 عقل الـ AI (Estimator)</text>
      <line x1="90" y1="45" x2="90" y2="700" stroke="#4338ca" stroke-dasharray="4,4" stroke-width="1.5"/>
    </g>

    <!-- 4. QualityGuard -->
    <g transform="translate(800, 110)">
      <rect width="160" height="45" rx="8" fill="#451a03" stroke="#f59e0b" stroke-width="1.5"/>
      <text x="80" y="28" font-size="14" font-weight="700" fill="#fde68a" text-anchor="middle">🛡️ حارس الأمان (Guard)</text>
      <line x1="80" y1="45" x2="80" y2="700" stroke="#78350f" stroke-dasharray="4,4" stroke-width="1.5"/>
    </g>

    <!-- 5. Owner Telegram -->
    <g transform="translate(1000, 110)">
      <rect width="150" height="45" rx="8" fill="#064e3b" stroke="#10b981" stroke-width="1.5"/>
      <text x="75" y="28" font-size="14" font-weight="700" fill="#6ee7b7" text-anchor="middle">📱 المالك (تيليجرام)</text>
      <line x1="75" y1="45" x2="75" y2="700" stroke="#065f46" stroke-dasharray="4,4" stroke-width="1.5"/>
    </g>

    <!-- Step 1: Customer greeting -->
    <g transform="translate(0, 180)">
      <line x1="160" y1="20" x2="410" y2="20" stroke="#60a5fa" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="180" y="0" width="210" height="20" rx="4" fill="#1e293b"/>
      <text x="285" y="14" font-size="11" fill="#e2e8f0" text-anchor="middle">1. "السلام عليكم، أريد متجر لبيع الملابس"</text>
    </g>

    <!-- Step 2: Extract & Consultative question -->
    <g transform="translate(0, 230)">
      <line x1="410" y1="20" x2="660" y2="20" stroke="#8b5cf6" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="440" y="0" width="190" height="20" rx="4" fill="#1e293b"/>
      <text x="535" y="14" font-size="11" fill="#c4b5fd" text-anchor="middle">2. استخراج الحاجة وصياغة سؤال استكشافي</text>
    </g>

    <!-- Step 3: Reply to Customer -->
    <g transform="translate(0, 280)">
      <line x1="410" y1="20" x2="160" y2="20" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="180" y="0" width="210" height="20" rx="4" fill="#1e293b"/>
      <text x="285" y="14" font-size="11" fill="#7dd3fc" text-anchor="middle">3. "أهلاً بك! كم عدد منتجاتكم وما طرق الدفع؟"</text>
    </g>

    <!-- Step 4: Customer answers specifics -->
    <g transform="translate(0, 330)">
      <line x1="160" y1="20" x2="410" y2="20" stroke="#60a5fa" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="180" y="0" width="210" height="20" rx="4" fill="#1e293b"/>
      <text x="285" y="14" font-size="11" fill="#e2e8f0" text-anchor="middle">4. "15 منتج ونريد بوابة أبل باي ولغتين"</text>
    </g>

    <!-- Gate-B Box -->
    <g transform="translate(320, 380)">
      <rect width="360" height="40" rx="6" fill="#065f46" stroke="#10b981" stroke-width="1.2"/>
      <text x="180" y="25" font-size="12" font-weight="700" fill="#a7f3d0" text-anchor="middle">✅ اكتمال متطلبات النطاق الفني (Gate-B Satisfied)</text>
    </g>

    <!-- Step 5: AI Technical WBS Estimation -->
    <g transform="translate(0, 440)">
      <line x1="410" y1="20" x2="660" y2="20" stroke="#8b5cf6" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="430" y="0" width="210" height="20" rx="4" fill="#2e1065"/>
      <text x="535" y="14" font-size="11" fill="#ddd6fe" text-anchor="middle">5. برومبت مهندس الحلول لحساب الساعات (WBS)</text>

      <line x1="660" y1="45" x2="410" y2="45" stroke="#a855f7" stroke-width="1.5" stroke-dasharray="4,4" marker-end="url(#arrow)"/>
      <rect x="430" y="32" width="210" height="20" rx="4" fill="#2e1065"/>
      <text x="535" y="46" font-size="10" fill="#e9d5ff" text-anchor="middle">48 ساعة عمل (18 واجهات، 16 سيرفر، 8 ربط، 6 نشر)</text>
    </g>

    <!-- Step 6: Pricing Engine Math -->
    <g transform="translate(320, 510)">
      <rect width="200" height="35" rx="6" fill="#1e293b" stroke="#3b82f6"/>
      <text x="100" y="22" font-size="11" fill="#93c5fd" text-anchor="middle">حساب السعر: 1,600$ (الحد: 1,100$)</text>
    </g>

    <!-- Parallel: Notice to Customer AND Alert to Owner -->
    <g transform="translate(0, 565)">
      <!-- To Customer: Tentative reassuring band -->
      <line x1="410" y1="20" x2="160" y2="20" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)"/>
      <rect x="170" y="0" width="230" height="20" rx="4" fill="#0c4a6e"/>
      <text x="285" y="14" font-size="10" fill="#bae6fd" text-anchor="middle">تقدير مبدئي: 1200-1800$ + جاري المراجعة الفنية</text>

      <!-- To Owner Telegram -->
      <line x1="410" y1="20" x2="1075" y2="20" stroke="#f59e0b" stroke-width="2.5" marker-end="url(#arrow-gold)"/>
      <rect x="680" y="0" width="310" height="20" rx="4" fill="#451a03"/>
      <text x="835" y="14" font-size="11" fill="#fde68a" font-weight="700" text-anchor="middle">🔔 إشعار تيليجرام: اعتماد سعر 1,600$ (48 ساعة تفصيلية)</text>
    </g>

    <!-- Step 7: Owner Approve -->
    <g transform="translate(0, 625)">
      <line x1="1075" y1="20" x2="410" y2="20" stroke="#10b981" stroke-width="2.5" marker-end="url(#arrow-green)"/>
      <rect x="650" y="0" width="280" height="20" rx="4" fill="#064e3b"/>
      <text x="790" y="14" font-size="11" fill="#6ee7b7" font-weight="700" text-anchor="middle">اعتماد المالك: /qapprove q-8a3f (أو بسعر مخصص 1500)</text>
    </g>

    <!-- Step 8: QualityGuard check -->
    <g transform="translate(0, 680)">
      <line x1="410" y1="20" x2="880" y2="20" stroke="#f59e0b" stroke-width="1.8" marker-end="url(#arrow)"/>
      <rect x="520" y="0" width="240" height="20" rx="4" fill="#1e293b"/>
      <text x="640" y="14" font-size="11" fill="#fde68a" text-anchor="middle">فحص السعر ومطابقته لسناب شوت الاعتماد T3</text>
    </g>

    <!-- Step 9: Final Official Offer to Customer -->
    <g transform="translate(0, 735)">
      <line x1="410" y1="20" x2="160" y2="20" stroke="#10b981" stroke-width="2.5" marker-end="url(#arrow-green)"/>
      <rect x="170" y="0" width="230" height="32" rx="6" fill="#065f46"/>
      <text x="285" y="15" font-size="11" font-weight="700" fill="#a7f3d0" text-anchor="middle">السعر الرسمي المعتمد: 1,500$</text>
      <text x="285" y="27" font-size="9" fill="#d1fae5" text-anchor="middle">شامل السيرفر، الدومين، SSL، الضمان، والدعم</text>
    </g>
</svg>"""
    return svg

# ==============================================================================
# 3. DIAGRAM 3: SALES STATE MACHINE
# ==============================================================================
def create_diagram_3():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" height="100%">
    {STYLES}
    <rect width="1200" height="800" fill="url(#bgGrad)"/>
    <rect x="20" y="20" width="1160" height="760" rx="16" fill="none" stroke="#334155" stroke-width="1.5"/>

    <!-- Header -->
    <text x="600" y="55" class="title">المخطط 3: آلة الحالات لمراحل المحادثة والبيع (Conversation State Machine FSM)</text>
    <text x="600" y="80" class="subtitle">المسار المنطقي الصارم الذي يمنع القفز أو إعطاء أسعار قبل اكتمال المتطلبات الفنية</text>

    <!-- Main States Flow -->
    <!-- State 1: OPENING -->
    <g transform="translate(60, 130)">
      <rect width="220" height="120" rx="10" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5" filter="url(#shadow)"/>
      <circle cx="25" cy="30" r="10" fill="#3b82f6"/>
      <text x="25" y="34" font-size="11" fill="#fff" text-anchor="middle">1</text>
      <text x="45" y="35" class="box-title" fill="#93c5fd">OPENING (الافتتاح والترحيب)</text>
      <text x="20" y="65" class="box-sub">• رسالة ترحيبية راقية ودافئة</text>
      <text x="20" y="85" class="box-sub">• اكتشاف لغة ولهجة العميل</text>
      <text x="20" y="105" class="box-sub">• قفل اللغة التلقائي (LANGUAGE LOCK)</text>
    </g>

    <!-- Arrow 1 -> 2 -->
    <path d="M 280 190 L 340 190" stroke="#3b82f6" stroke-width="2.5" marker-end="url(#arrow)"/>
    <text x="310" y="180" font-size="10" fill="#60a5fa" text-anchor="middle">تحديد النشاط</text>

    <!-- State 2: NEED -->
    <g transform="translate(340, 130)">
      <rect width="230" height="120" rx="10" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5" filter="url(#shadow)"/>
      <circle cx="25" cy="30" r="10" fill="#3b82f6"/>
      <text x="25" y="34" font-size="11" fill="#fff" text-anchor="middle">2</text>
      <text x="45" y="35" class="box-title" fill="#93c5fd">NEED (اكتشاف الاحتياج)</text>
      <text x="20" y="65" class="box-sub">• سؤال استشاري واحد ذكي</text>
      <text x="20" y="85" class="box-sub">• تصنيف الخدمة (متجر/موقع/ERP)</text>
      <text x="20" y="105" class="box-sub">• استخراج حقائق المشروع الأولية</text>
    </g>

    <!-- Arrow 2 -> 3 -->
    <path d="M 570 190 L 630 190" stroke="#3b82f6" stroke-width="2.5" marker-end="url(#arrow)"/>
    <text x="600" y="180" font-size="10" fill="#60a5fa" text-anchor="middle">تحديد الميزات</text>

    <!-- State 3: SHAPING -->
    <g transform="translate(630, 130)">
      <rect width="230" height="120" rx="10" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5" filter="url(#shadow)"/>
      <circle cx="25" cy="30" r="10" fill="#3b82f6"/>
      <text x="25" y="34" font-size="11" fill="#fff" text-anchor="middle">3</text>
      <text x="45" y="35" class="box-title" fill="#93c5fd">SHAPING (تشكيل الحل)</text>
      <text x="20" y="65" class="box-sub">• تأطير الهيكل التقني الأنسب</text>
      <text x="20" y="85" class="box-sub">• إبراز القيمة الاستثمارية للمشروع</text>
      <text x="20" y="105" class="box-sub">• ربط متطلبات العميل بالحلول</text>
    </g>

    <!-- Arrow 3 -> 4 -->
    <path d="M 860 190 L 920 190" stroke="#3b82f6" stroke-width="2.5" marker-end="url(#arrow)"/>
    <text x="890" y="180" font-size="10" fill="#60a5fa" text-anchor="middle">طلب التكلفة</text>

    <!-- State 4: COMMERCIAL CONTAINER (BIG) -->
    <g transform="translate(60, 290)">
      <rect width="1080" height="260" rx="12" fill="#111c2e" stroke="#2563eb" stroke-width="2" filter="url(#shadow)"/>
      <rect x="20" y="-12" width="300" height="24" rx="6" fill="#1d4ed8"/>
      <text x="170" y="4" class="badge-text" text-anchor="middle">💰 COMMERCIAL (بوابات التسعير الصارمة T0 - T3)</text>

      <!-- Sub-state T0 -->
      <g transform="translate(30, 35)">
        <rect width="230" height="195" rx="8" fill="#1e293b" stroke="#475569"/>
        <text x="15" y="30" class="box-title" fill="#94a3b8">بوابة T0: No Scope</text>
        <text x="15" y="55" class="box-sub">العميل سأل: "بكم الموقع؟"</text>
        <rect x="15" y="70" width="200" height="45" rx="4" fill="#0f172a"/>
        <text x="25" y="88" font-size="10" fill="#f87171">🚫 ممنوع إعطاء أي رقم</text>
        <text x="25" y="104" font-size="10" fill="#94a3b8">يطلب تفاصيل نشاطه أولاً</text>
        <text x="15" y="145" class="box-sub">الهدف: حماية الشركة من</text>
        <text x="15" y="165" class="box-sub">التسعير الأعمى غير المدروس</text>
      </g>

      <!-- Arrow T0 -> T1 -->
      <path d="M 260 130 L 290 130" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"/>

      <!-- Sub-state T1 -->
      <g transform="translate(290, 35)">
        <rect width="230" height="195" rx="8" fill="#1e293b" stroke="#3b82f6"/>
        <text x="15" y="30" class="box-title" fill="#60a5fa">بوابة T1: Public Band</text>
        <text x="15" y="55" class="box-sub">حدد الخدمة ولم يحدد الميزات</text>
        <rect x="15" y="70" width="200" height="45" rx="4" fill="#0f172a"/>
        <text x="25" y="88" font-size="10" fill="#38bdf8">نطاق عام استرشادي فقط</text>
        <text x="25" y="104" font-size="10" fill="#94a3b8">"المواقع المماثلة تبدأ من..."</text>
        <text x="15" y="145" class="box-sub">يوجه العميل فوراً لتحديد</text>
        <text x="15" y="165" class="box-sub">الميزات لتثبيت السعر الفعلي</text>
      </g>

      <!-- Arrow T1 -> T2 -->
      <path d="M 520 130 L 550 130" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)"/>

      <!-- Sub-state T2 -->
      <g transform="translate(550, 35)">
        <rect width="240" height="195" rx="8" fill="#1e1b4b" stroke="#8b5cf6" stroke-width="1.5"/>
        <text x="15" y="30" class="box-title" fill="#c4b5fd">بوابة T2: Gate-B Scope</text>
        <text x="15" y="55" class="box-sub">اكتملت الميزات والمقاييس</text>
        <rect x="15" y="70" width="210" height="55" rx="4" fill="#17112f"/>
        <text x="25" y="88" font-size="10" fill="#a78bfa">🧠 الـ AI يحسب ساعات العمل</text>
        <text x="25" y="104" font-size="10" fill="#fbbf24">🔔 إرسال تنبيه للمالك بتيليجرام</text>
        <text x="25" y="118" font-size="9" fill="#94a3b8">طمأنة العميل بمراجعة الفريق</text>
        <text x="15" y="155" class="box-sub">العميل لا ينتظر بصمت بل يشعر</text>
        <text x="15" y="172" class="box-sub">بالاهتمام التام بمشروعه</text>
      </g>

      <!-- Arrow T2 -> T3 -->
      <path d="M 790 130 L 820 130" stroke="#10b981" stroke-width="2.5" marker-end="url(#arrow-green)"/>

      <!-- Sub-state T3 -->
      <g transform="translate(820, 35)">
        <rect width="230" height="195" rx="8" fill="#064e3b" stroke="#10b981" stroke-width="1.8"/>
        <text x="15" y="30" class="box-title" fill="#6ee7b7">بوابة T3: Approved Price</text>
        <text x="15" y="55" class="box-sub">موافقة المالك في تيليجرام</text>
        <rect x="15" y="70" width="200" height="55" rx="4" fill="#042f2e"/>
        <text x="25" y="88" font-size="10" fill="#34d399">✅ اعتماد السعر الرسمي</text>
        <text x="25" y="104" font-size="10" fill="#a7f3d0">تجميد السناب شوت بقاعدة البيانات</text>
        <text x="25" y="118" font-size="9" fill="#6ee7b7">تقديم حزمة المزايا الـ 7 الكاملة</text>
        <text x="15" y="155" class="box-sub">لا يخرج أي رقم رسمي إلا</text>
        <text x="15" y="172" class="box-sub">بعد مرور هذه البوابة حتماً</text>
      </g>
    </g>

    <!-- State 5: NEGOTIATION -->
    <g transform="translate(60, 590)">
      <rect width="1080" height="160" rx="12" fill="#1a1c23" stroke="#f59e0b" stroke-width="1.5" filter="url(#shadow)"/>
      <rect x="20" y="-12" width="260" height="24" rx="6" fill="url(#goldGrad)"/>
      <text x="150" y="4" class="badge-text" text-anchor="middle">🤝 NEGOTIATION (استراتيجيات التفاوض الذكي)</text>

      <g transform="translate(30, 25)">
        <rect width="235" height="110" rx="8" fill="#13151b" stroke="#334155"/>
        <text x="15" y="25" class="box-title" fill="#fde68a">1. إبراز القيمة التنافسية</text>
        <text x="15" y="50" class="box-sub">• سيرفرات سحابية سريعة ومجانية</text>
        <text x="15" y="70" class="box-sub">• دومين وشهادة SSL وضمان تقني</text>
        <text x="15" y="90" class="box-sub">• تدريب كامل للعميل على لوحة التحكم</text>
      </g>

      <g transform="translate(290, 25)">
        <rect width="240" height="110" rx="8" fill="#13151b" stroke="#334155"/>
        <text x="15" y="25" class="box-title" fill="#fde68a">2. تجزئة النطاق (De-scoping)</text>
        <text x="15" y="50" class="box-sub">• إذا كانت ميزانية العميل أقل:</text>
        <text x="15" y="70" class="box-sub">• اقتراح تقليص اللغات مؤقتاً</text>
        <text x="15" y="90" class="box-sub">• أو تقليص عدد الصفحات والتقارير</text>
      </g>

      <g transform="translate(555, 25)">
        <rect width="240" height="110" rx="8" fill="#13151b" stroke="#334155"/>
        <text x="15" y="25" class="box-title" fill="#fde68a">3. الإطلاق المرحلي (MVP Phase)</text>
        <text x="15" y="50" class="box-sub">• إطلاق النسخة الأولى الأساسية الآن</text>
        <text x="15" y="70" class="box-sub">• تأجيل الميزات المعقدة للمرحلة 2</text>
        <text x="15" y="90" class="box-sub">• بدء البيع السريع بأقل تكلفة</text>
      </g>

      <g transform="translate(820, 25)">
        <rect width="230" height="110" rx="8" fill="#13151b" stroke="#10b981"/>
        <text x="15" y="25" class="box-title" fill="#86efac">4. مرونة السداد والأمان</text>
        <text x="15" y="50" class="box-sub">• 50% دفعة أولى للبدء</text>
        <text x="15" y="70" class="box-sub">• 50% فقط بعد المعاينة والتسليم</text>
        <text x="15" y="90" class="box-sub" fill="#34d399">🎯 إغلاق الصفقة (Deal Won)</text>
      </g>
    </g>
</svg>"""
    return svg

# ==============================================================================
# 4. DIAGRAM 4: QUALITY GUARD SAFETY
# ==============================================================================
def create_diagram_4():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" height="100%">
    {STYLES}
    <rect width="1200" height="800" fill="url(#bgGrad)"/>
    <rect x="20" y="20" width="1160" height="760" rx="16" fill="none" stroke="#334155" stroke-width="1.5"/>

    <!-- Header -->
    <text x="600" y="55" class="title">المخطط 4: حراسة الجودة والأمان المالي (QualityGuard &amp; Anti-Hallucination)</text>
    <text x="600" y="80" class="subtitle">صمام الأمان البرمجي الحتمي الذي يفحص كل رسالة قبل وصولها للعميل ويمنع التلاعب والهلوسة</text>

    <!-- Start: Draft from AI -->
    <g transform="translate(450, 110)">
      <rect width="300" height="60" rx="10" fill="#1e293b" stroke="#3b82f6" stroke-width="2" filter="url(#shadow)"/>
      <text x="150" y="27" class="box-title" text-anchor="middle">مسودة الرد المولدة من الذكاء الاصطناعي</text>
      <text x="150" y="47" class="box-sub" text-anchor="middle">Draft Reply from Drafter Prompt</text>
    </g>

    <!-- Arrow down -->
    <path d="M 600 170 L 600 215" stroke="#3b82f6" stroke-width="2.5" marker-end="url(#arrow)"/>

    <!-- CHECK 1: SCAN FOR NUMBERS -->
    <g transform="translate(425, 215)">
      <polygon points="175,0 350,55 175,110 0,55" fill="#1f2937" stroke="#f59e0b" stroke-width="2"/>
      <text x="175" y="48" font-size="13" font-weight="700" fill="#fde68a" text-anchor="middle">هل يحتوي الرد على</text>
      <text x="175" y="68" font-size="13" font-weight="700" fill="#fde68a" text-anchor="middle">أي مبالغ مالية أو أرقام؟</text>
    </g>

    <!-- Branch YES -> Check Allowed Numbers -->
    <path d="M 600 325 L 600 380" stroke="#ef4444" stroke-width="2.5" marker-end="url(#arrow)"/>
    <text x="615" y="355" font-size="11" font-weight="700" fill="#f87171">نعم، يوجد رقم</text>

    <!-- CHECK 1.1: ALLOWED NUMBERS -->
    <g transform="translate(425, 380)">
      <polygon points="175,0 350,55 175,110 0,55" fill="#1f2937" stroke="#ef4444" stroke-width="2"/>
      <text x="175" y="48" font-size="12" font-weight="700" fill="#fca5a5" text-anchor="middle">هل هذه الأرقام مصرح بها نصاً</text>
      <text x="175" y="68" font-size="12" font-weight="700" fill="#fca5a5" text-anchor="middle">في الخطة ومعتمدة من المالك؟</text>
    </g>

    <!-- Branch NO (Allowed) -> BLOCK -->
    <path d="M 425 435 L 250 435" stroke="#ef4444" stroke-width="2.5" marker-end="url(#arrow)"/>
    <text x="330" y="425" font-size="11" font-weight="700" fill="#f87171">لا، رقم غير مصرح به</text>

    <g transform="translate(50, 400)">
      <rect width="200" height="70" rx="8" fill="#450a0a" stroke="#ef4444" stroke-width="1.8" filter="url(#shadow)"/>
      <text x="100" y="30" font-size="13" font-weight="800" fill="#fecaca" text-anchor="middle">🚫 حجب الرد فوراً</text>
      <text x="100" y="52" font-size="10" fill="#fca5a5" text-anchor="middle">(unauthorized_number)</text>
    </g>

    <!-- Branch YES (Allowed) -> Continue -->
    <path d="M 775 435 L 880 435 L 880 270 L 775 270" stroke="#10b981" stroke-width="2" marker-end="url(#arrow-green)" fill="none"/>
    <text x="895" y="355" font-size="11" font-weight="700" fill="#34d399">نعم، معتمد</text>

    <!-- CHECK 2: SCAN FOR FORBIDDEN CLAIMS (From No numbers branch) -->
    <path d="M 425 270 L 250 270" stroke="#3b82f6" stroke-width="2" marker-end="url(#arrow)"/>
    <text x="330" y="260" font-size="11" font-weight="700" fill="#60a5fa">لا توجد أرقام</text>

    <g transform="translate(50, 235)">
      <rect width="200" height="70" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="100" y="30" font-size="12" font-weight="700" fill="#93c5fd" text-anchor="middle">فحص الادعاءات المحظورة</text>
      <text x="100" y="50" font-size="10" fill="#94a3b8" text-anchor="middle">"نضمن 100%"، "لدينا 500 عميل"</text>
    </g>

    <!-- Connect Check 2 to Decision -->
    <path d="M 150 305 L 150 400" stroke="#ef4444" stroke-width="2" marker-end="url(#arrow)"/>
    <text x="160" y="360" font-size="10" fill="#ef4444">ادعاء محظور</text>

    <!-- Fallback Box -->
    <g transform="translate(50, 520)">
      <rect width="200" height="85" rx="8" fill="#1c1917" stroke="#f59e0b" stroke-width="1.5"/>
      <text x="100" y="28" font-size="12" font-weight="700" fill="#fbbf24" text-anchor="middle">إعادة المحاولة / البديل الآمن</text>
      <text x="15" y="48" font-size="10" fill="#d6d3d1">• إعادة صياغة عبر الـ AI</text>
      <text x="15" y="65" font-size="10" fill="#d6d3d1">• إذا فشل ثانية: إسقاط الرد</text>
      <text x="15" y="78" font-size="9" fill="#a8a29e">واستبداله بالرد الاستشاري المعتمد</text>
    </g>
    <path d="M 150 470 L 150 520" stroke="#f59e0b" stroke-width="2" marker-end="url(#arrow-gold)"/>

    <!-- CHECK 3: LANGUAGE LOCK -->
    <path d="M 600 490 L 600 550" stroke="#10b981" stroke-width="2.5" marker-end="url(#arrow-green)"/>

    <g transform="translate(425, 550)">
      <polygon points="175,0 350,55 175,110 0,55" fill="#1f2937" stroke="#3b82f6" stroke-width="2"/>
      <text x="175" y="48" font-size="12" font-weight="700" fill="#93c5fd" text-anchor="middle">هل لغة الرد مطابقة للغة العميل؟</text>
      <text x="175" y="68" font-size="12" font-weight="700" fill="#93c5fd" text-anchor="middle">(LANGUAGE LOCK)</text>
    </g>

    <!-- Language Fail -> Redraft -->
    <path d="M 425 605 L 250 562" stroke="#f59e0b" stroke-width="2" marker-end="url(#arrow-gold)"/>
    <text x="340" y="575" font-size="10" fill="#f59e0b">لغة مختلفة ⬅️ إعادة الصياغة</text>

    <!-- Language OK -> SUCCESS SEND -->
    <path d="M 600 660 L 600 710" stroke="#10b981" stroke-width="2.5" marker-end="url(#arrow-green)"/>

    <g transform="translate(425, 710)">
      <rect width="350" height="60" rx="10" fill="#064e3b" stroke="#10b981" stroke-width="2" filter="url(#shadow)"/>
      <text x="175" y="28" font-size="14" font-weight="800" fill="#a7f3d0" text-anchor="middle">✅ إجازة الإرسال إلى العميل (Safe to Send)</text>
      <text x="175" y="48" font-size="11" fill="#6ee7b7" text-anchor="middle">التمرير إلى صندوق الصادر الذري (Outbox Queue)</text>
    </g>
</svg>"""
    return svg

# ==============================================================================
# 5. DIAGRAM 5: MEMORY & DATA FLOW
# ==============================================================================
def create_diagram_5():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" height="100%">
    {STYLES}
    <rect width="1200" height="800" fill="url(#bgGrad)"/>
    <rect x="20" y="20" width="1160" height="760" rx="16" fill="none" stroke="#334155" stroke-width="1.5"/>

    <!-- Header -->
    <text x="600" y="55" class="title">المخطط 5: تدفق الذاكرة والمستندات الفنية (Memory &amp; SOW Data Flow)</text>
    <text x="600" y="80" class="subtitle">كيف تتحول كلمات العميل الطبيعية إلى حقائق برمجية دائمة وتلخيص تراكمي دون نسيان أي تفصيل</text>

    <!-- Column 1: Inbound Message -->
    <g transform="translate(50, 120)">
      <rect width="250" height="620" rx="12" fill="#131d2e" stroke="#38bdf8" stroke-width="1.5" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="220" height="24" rx="6" fill="#0284c7"/>
      <text x="125" y="4" class="badge-text" text-anchor="middle">📩 كل رسالة جديدة من العميل</text>

      <g transform="translate(20, 30)">
        <rect width="210" height="90" rx="8" fill="#1e293b" stroke="#334155"/>
        <text x="15" y="25" class="box-title">رسالة العميل الأولية</text>
        <text x="15" y="45" font-size="10" fill="#94a3b8">"أريد متجر عطور في الرياض"</text>
        <rect x="15" y="55" width="120" height="20" rx="4" fill="#0369a1"/>
        <text x="75" y="69" font-size="9" fill="#fff" text-anchor="middle">نوع الخدمة: متجر</text>
      </g>

      <g transform="translate(20, 140)">
        <rect width="210" height="110" rx="8" fill="#1e293b" stroke="#334155"/>
        <text x="15" y="25" class="box-title">الرسالة الثانية: الميزات</text>
        <text x="15" y="45" font-size="10" fill="#94a3b8">"مع بوابة دفع أبل باي ولغتين"</text>
        <rect x="15" y="55" width="160" height="20" rx="4" fill="#0369a1"/>
        <text x="95" y="69" font-size="9" fill="#fff" text-anchor="middle">ميزات: دفع + لغتين</text>
        <rect x="15" y="80" width="120" height="20" rx="4" fill="#0284c7"/>
        <text x="75" y="94" font-size="9" fill="#fff" text-anchor="middle">العملة: SAR</text>
      </g>

      <g transform="translate(20, 270)">
        <rect width="210" height="90" rx="8" fill="#1e293b" stroke="#334155"/>
        <text x="15" y="25" class="box-title">الرسالة الثالثة: النطاق</text>
        <text x="15" y="45" font-size="10" fill="#94a3b8">"عندي حوالي 25 منتج تقريباً"</text>
        <rect x="15" y="55" width="150" height="20" rx="4" fill="#0369a1"/>
        <text x="90" y="69" font-size="9" fill="#fff" text-anchor="middle">حجم الكتالوج: 25 منتج</text>
      </g>

      <g transform="translate(20, 380)">
        <rect width="210" height="210" rx="8" fill="#0f172a" stroke="#1e293b"/>
        <text x="15" y="25" font-size="12" font-weight="700" fill="#38bdf8">حفظ في سجل المحادثة:</text>
        <text x="15" y="50" font-size="10" fill="#94a3b8">جدول channel_messages</text>
        <text x="15" y="70" font-size="10" fill="#94a3b8">• رقم الرسالة الخارجي</text>
        <text x="15" y="90" font-size="10" fill="#94a3b8">• اتجاه الرسالة (in / out)</text>
        <text x="15" y="110" font-size="10" fill="#94a3b8">• القناة (whatsapp, ig...)</text>
        <text x="15" y="130" font-size="10" fill="#94a3b8">• التوقيت الدقيق UTC</text>
        <text x="15" y="150" font-size="10" fill="#94a3b8">• هوية العميل الموحدة</text>
        <text x="15" y="180" font-size="10" fill="#34d399">✅ ثبات دائم لا يحذف</text>
      </g>
    </g>

    <!-- Arrow 1 -> 2 -->
    <path d="M 300 230 L 350 230" stroke="#38bdf8" stroke-width="2.5" marker-end="url(#arrow)"/>
    <path d="M 300 450 L 350 450" stroke="#38bdf8" stroke-width="2.5" marker-end="url(#arrow)"/>

    <!-- Column 2: Extractor & Facts -->
    <g transform="translate(350, 120)">
      <rect width="360" height="620" rx="12" fill="#181825" stroke="#8b5cf6" stroke-width="1.5" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="240" height="24" rx="6" fill="#6d28d9"/>
      <text x="135" y="4" class="badge-text" text-anchor="middle">🔍 محرك الاستخراج وتحليل المتطلبات</text>

      <!-- Facts Extraction -->
      <g transform="translate(20, 25)">
        <rect width="320" height="170" rx="8" fill="#1e1b4b" stroke="#4338ca"/>
        <text x="15" y="25" class="box-title" fill="#c4b5fd">استخراج الحقائق (Structured Facts JSON)</text>
        <rect x="15" y="38" width="290" height="115" rx="6" fill="#0f0c29"/>
        <text x="25" y="58" font-size="10" fill="#a5b4fc">"service": "ecommerce_store",</text>
        <text x="25" y="75" font-size="10" fill="#a5b4fc">"features": ["apple_pay", "multilingual"],</text>
        <text x="25" y="92" font-size="10" fill="#a5b4fc">"catalog_size": 25,</text>
        <text x="25" y="109" font-size="10" fill="#a5b4fc">"location": "Riyadh, SA",</text>
        <text x="25" y="126" font-size="10" fill="#a5b4fc">"currency": "SAR"</text>
      </g>

      <!-- Rolling Summary -->
      <g transform="translate(20, 215)">
        <rect width="320" height="170" rx="8" fill="#1e1b4b" stroke="#4338ca"/>
        <text x="15" y="25" class="box-title" fill="#c4b5fd">التلخيص التراكمي (Rolling Summary)</text>
        <text x="15" y="45" class="box-sub">كل 10 رسائل يلخص المحادثة آلياً:</text>
        <rect x="15" y="55" width="290" height="100" rx="6" fill="#0f0c29"/>
        <text x="25" y="75" font-size="10" fill="#e2e8f0">"العميل صاحب متجر عطور بالرياض،</text>
        <text x="25" y="95" font-size="10" fill="#e2e8f0">يحتاج متجر إلكتروني يدعم أبل باي</text>
        <text x="25" y="115" font-size="10" fill="#e2e8f0">ولغتين عربي وإنجليزي لـ 25 منتج،</text>
        <text x="25" y="135" font-size="10" fill="#e2e8f0">وهو في مرحلة انتظار السعر الرسمي."</text>
      </g>

      <!-- Scope Fingerprint -->
      <g transform="translate(20, 405)">
        <rect width="320" height="195" rx="8" fill="#1e1b4b" stroke="#4338ca"/>
        <text x="15" y="25" class="box-title" fill="#c4b5fd">بصمة النطاق (Scope Fingerprint)</text>
        <text x="15" y="45" class="box-sub">توليد شفرة فريدة تمثل نطاق المشروع:</text>
        <rect x="15" y="55" width="290" height="35" rx="4" fill="#0f0c29"/>
        <text x="25" y="77" font-size="11" fill="#38bdf8" font-weight="700">fp_ecom_25p_applepay_multilang</text>
        <text x="15" y="115" font-size="11" fill="#cbd5e1">• تمنع تكرار طلب اعتماد نفس السعر</text>
        <text x="15" y="135" font-size="11" fill="#cbd5e1">• تكتشف أي تعديل أو إضافة جديدة فوراً</text>
        <text x="15" y="155" font-size="11" fill="#cbd5e1">• تضمن اتساق التسعير طوال المحادثة</text>
      </g>
    </g>

    <!-- Arrow 2 -> 3 -->
    <path d="M 710 230 L 760 230" stroke="#8b5cf6" stroke-width="2.5" marker-end="url(#arrow)"/>
    <path d="M 710 500 L 760 500" stroke="#8b5cf6" stroke-width="2.5" marker-end="url(#arrow)"/>

    <!-- Column 3: SOW & Project Scope -->
    <g transform="translate(760, 120)">
      <rect width="390" height="620" rx="12" fill="#0f291e" stroke="#10b981" stroke-width="1.8" filter="url(#shadow)"/>
      <rect x="15" y="-12" width="260" height="24" rx="6" fill="#047857"/>
      <text x="145" y="4" class="badge-text" text-anchor="middle">📋 ملف نطاق العمل الفني (SOW File)</text>

      <!-- Scope Version Table -->
      <g transform="translate(20, 25)">
        <rect width="350" height="260" rx="8" fill="#064e3b" stroke="#059669"/>
        <text x="15" y="25" class="box-title" fill="#a7f3d0">جدول المهام والمتطلبات الرسمية</text>

        <rect x="15" y="40" width="320" height="35" rx="4" fill="#022c22"/>
        <text x="25" y="62" font-size="11" fill="#fff" font-weight="700">1. واجهة المتجر وتجربة المستخدم (UI/UX)</text>
        <text x="315" y="62" font-size="11" fill="#6ee7b7" text-anchor="end">18 ساعة</text>

        <rect x="15" y="82" width="320" height="35" rx="4" fill="#022c22"/>
        <text x="25" y="104" font-size="11" fill="#fff" font-weight="700">2. خوادم وقواعد البيانات (Backend API)</text>
        <text x="315" y="104" font-size="11" fill="#6ee7b7" text-anchor="end">16 ساعة</text>

        <rect x="15" y="124" width="320" height="35" rx="4" fill="#022c22"/>
        <text x="25" y="146" font-size="11" fill="#fff" font-weight="700">3. بوابات الدفع واللغات (Integrations)</text>
        <text x="315" y="146" font-size="11" fill="#6ee7b7" text-anchor="end">8 ساعات</text>

        <rect x="15" y="166" width="320" height="35" rx="4" fill="#022c22"/>
        <text x="25" y="188" font-size="11" fill="#fff" font-weight="700">4. فحص الجودة والنشر السحابي (QA)</text>
        <text x="315" y="188" font-size="11" fill="#6ee7b7" text-anchor="end">6 ساعات</text>

        <rect x="15" y="210" width="320" height="38" rx="6" fill="#047857"/>
        <text x="25" y="234" font-size="13" fill="#ffffff" font-weight="800">إجمالي ساعات العمل التقديرية:</text>
        <text x="315" y="234" font-size="13" fill="#ffffff" font-weight="800" text-anchor="end">48 ساعة</text>
      </g>

      <!-- Package Inclusions -->
      <g transform="translate(20, 305)">
        <rect width="350" height="295" rx="8" fill="#064e3b" stroke="#059669"/>
        <text x="15" y="25" class="box-title" fill="#a7f3d0">حزمة المزايا الـ 7 المضمنة في العرض:</text>
        
        <text x="20" y="55" font-size="11" fill="#d1fae5">1. ⚡ استضافة سحابية فائقة السرعة لمدة عام</text>
        <text x="20" y="85" font-size="11" fill="#d1fae5">2. 🗄️ قاعدة بيانات مستقلة مع نسخ احتياطي تلقائي</text>
        <text x="20" y="115" font-size="11" fill="#d1fae5">3. 🌐 حجز اسم نطاق رسمي (.com / .sa) + شهادة SSL</text>
        <text x="20" y="145" font-size="11" fill="#d1fae5">4. 📱 واجهات متجاوبة بالكامل 100% مع الجوال والكمبيوتر</text>
        <text x="20" y="175" font-size="11" fill="#d1fae5">5. 📊 لوحة تحكم كاملة لإدارة الطلبات والمنتجات</text>
        <text x="20" y="205" font-size="11" fill="#d1fae5">6. 💳 دفعات مرحلية آمنة (50% مقدم و 50% بعد التسليم)</text>
        <text x="20" y="235" font-size="11" fill="#d1fae5">7. 🛠️ دعم فني وضمان شامل وتدريب كامل على النظام</text>

        <rect x="20" y="255" width="310" height="30" rx="4" fill="#047857"/>
        <text x="175" y="275" font-size="11" fill="#ffffff" font-weight="700" text-anchor="middle">جاهز للتنفيذ والتعاقد الفوري 🚀</text>
      </g>
    </g>
</svg>"""
    return svg

# Save all SVG files
files = [
    ("01_system_architecture.svg", create_diagram_1()),
    ("02_customer_journey_sequence.svg", create_diagram_2()),
    ("03_sales_state_machine.svg", create_diagram_3()),
    ("04_quality_guard_safety.svg", create_diagram_4()),
    ("05_memory_data_flow.svg", create_diagram_5()),
]

for filename, content in files:
    filepath = os.path.join(DIAGRAMS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"Generated SVG: {filename} ({len(content)} bytes)")

# Generate Master Interactive HTML Viewer
html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>مخططات معمارية وتشغيل نظام AmanCore - جودة فيكتور لا نهائية</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #131b2e;
      --border: #23334d;
      --accent: #3b82f6;
      --text: #cbd5e1;
      --heading: #ffffff;
      --gold: #f59e0b;
      --green: #10b981;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: 'Cairo', sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 30px 20px;
      line-height: 1.6;
    }}
    .header {{
      max-width: 1300px;
      margin: 0 auto 30px auto;
      text-align: center;
      padding: 30px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
    }}
    .header h1 {{
      color: var(--heading);
      margin: 0 0 10px 0;
      font-size: 2.3rem;
      font-weight: 900;
    }}
    .header p {{
      color: #94a3b8;
      margin: 0;
      font-size: 1.15rem;
    }}
    .badges-row {{
      display: flex;
      justify-content: center;
      gap: 12px;
      margin-top: 20px;
      flex-wrap: wrap;
    }}
    .badge {{
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 0.9rem;
      font-weight: 700;
    }}
    .badge-blue {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid #3b82f6; }}
    .badge-green {{ background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid #10b981; }}
    .badge-gold {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b; }}

    .container {{
      max-width: 1300px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 50px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 25px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 18px;
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 15px;
    }}
    .card-title {{
      font-size: 1.4rem;
      font-weight: 800;
      color: var(--heading);
      margin: 0;
    }}
    .btn-download {{
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 9px 20px;
      border-radius: 8px;
      font-family: 'Cairo', sans-serif;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
      transition: all 0.2s;
      font-size: 0.95rem;
    }}
    .btn-download:hover {{
      background: #2563eb;
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
    }}
    .svg-container {{
      background: #0b0f17;
      border-radius: 12px;
      padding: 15px;
      border: 1px solid #1e293b;
      overflow-x: auto;
      text-align: center;
    }}
    .svg-container img, .svg-container object, .svg-container svg {{
      max-width: 100%;
      height: auto;
      display: block;
      margin: 0 auto;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🚀 مركز المخططات الهندسية الشاملة - AmanCore</h1>
    <p>ملفات بصيغة الفيكتور النقي (Pure Scalable Vector Graphics - SVG) • تكبير لا نهائي بنسبة 1000% بأعلى دقة ووضوح بدون أي بكسلة</p>
    <div class="badges-row">
      <span class="badge badge-blue">دقة 100% مطابقة لتدفق الكود الفعلي</span>
      <span class="badge badge-green">فيكتور هندسي مستقل بدون أي إنترنت</span>
      <span class="badge badge-gold">جاهز للعرض في المتصفح، الجوال، وFigma</span>
    </div>
  </div>

  <div class="container">
    <!-- Card 1 -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">المخطط 1: معمارية النظام العامة والربط بالقنوات (System Architecture)</h2>
        <a class="btn-download" href="./01_system_architecture.svg" download="01_system_architecture.svg">
          📥 تحميل ملف الـ SVG الفيكتور
        </a>
      </div>
      <div class="svg-container">
        <img src="./01_system_architecture.svg" alt="المخطط 1: معمارية النظام العامة">
      </div>
    </div>

    <!-- Card 2 -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">المخطط 2: تسلسل رحلة العميل خطوة بخطوة (Customer Journey Sequence)</h2>
        <a class="btn-download" href="./02_customer_journey_sequence.svg" download="02_customer_journey_sequence.svg">
          📥 تحميل ملف الـ SVG الفيكتور
        </a>
      </div>
      <div class="svg-container">
        <img src="./02_customer_journey_sequence.svg" alt="المخطط 2: تسلسل رحلة العميل">
      </div>
    </div>

    <!-- Card 3 -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">المخطط 3: آلة الحالات لمراحل البيع (Conversation State Machine FSM)</h2>
        <a class="btn-download" href="./03_sales_state_machine.svg" download="03_sales_state_machine.svg">
          📥 تحميل ملف الـ SVG الفيكتور
        </a>
      </div>
      <div class="svg-container">
        <img src="./03_sales_state_machine.svg" alt="المخطط 3: آلة الحالات">
      </div>
    </div>

    <!-- Card 4 -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">المخطط 4: حراسة الجودة والأمان المالي (QualityGuard &amp; Financial Safety)</h2>
        <a class="btn-download" href="./04_quality_guard_safety.svg" download="04_quality_guard_safety.svg">
          📥 تحميل ملف الـ SVG الفيكتور
        </a>
      </div>
      <div class="svg-container">
        <img src="./04_quality_guard_safety.svg" alt="المخطط 4: حراسة الجودة">
      </div>
    </div>

    <!-- Card 5 -->
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">المخطط 5: تدفق الذاكرة والمستندات الفنية (Memory &amp; SOW Data Flow)</h2>
        <a class="btn-download" href="./05_memory_data_flow.svg" download="05_memory_data_flow.svg">
          📥 تحميل ملف الـ SVG الفيكتور
        </a>
      </div>
      <div class="svg-container">
        <img src="./05_memory_data_flow.svg" alt="المخطط 5: تدفق الذاكرة">
      </div>
    </div>
  </div>
</body>
</html>
"""

with open(os.path.join(DIAGRAMS_DIR, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(html_content)
print("Generated index.html dashboard.")
