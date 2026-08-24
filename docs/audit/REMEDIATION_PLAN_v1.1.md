# AMANCORE — PRODUCTION REMEDIATION PLAN v1.1

> **الإصدار:** 1.1 (مُراجَعة ومُصلَّدة في المكان — Final In-Place Review) · **التاريخ:** 2026-08-24 · **الحالة:** انظر [Final Review Status](#final-review-status) أسفل الوثيقة
> **المدخلات:** [PRODUCTION_AUDIT_2026-08-24.md](./PRODUCTION_AUDIT_2026-08-24.md) · [REMEDIATION_PLAN.md](./REMEDIATION_PLAN.md) (v1.0 — سجل تاريخي، غير معدَّل)
> **تحقق مخبري مدعوم بالأدلة (قراءة فقط):** `.env` ‏664 · `~/.bash_history` يحوي **12 مطابقة** لأنماط توكنات · `whatsapp.py` يستخرج WAMID من استجابة 200 · الوحدتان `amancore-webhook.service` + `amancore-scheduler.service` فعّالتان · `STATUSES` الحالية `{queued, processing, sent, failed, dead, cancelled}` · `_record_status` يطابق عبر `provider_message_id`.

---

## 🚀 IMPLEMENTATION PROGRESS — محدَّث حياً

**آخر تحديث:** 2026-08-24 · **الاختبارات:** 498/498 ✓ (خط الأساس 458 +40 جديد) · **health:** 200

### منجز (GO)

| الترتيب | المهمة | Commit | الدليل التشغيلي |
|---|---|---|---|
| G0 | خط الأساس + artifact تراجع | e25f05f | نسخة DB سليمة 802KB sha256=ef2facf4 + لقطة schema + WAL checkpoint |
| OBS-101 | ربط السجلات + تعقيم أسرار + correlation | d9a31c1 | **رحلة رسالة كاملة من journald بcid واحد** (received→route→draft→outbox→200) |
| OBS-102 | بصمات التنبيهات + نوافذ خطورة C15/H60/M240 + إعادات نقل ×3 | 3db46d7 | اختبار e2e: تنبيهان متمايزان بنفس الساعة وصلا كلاهما |
| BAK-103 | نسخ صادقة: raise+verify مدمج+restore_test شهري+مسار مهيأ | 54d34fb | نسخة حية created+verified على قاعدة الإنتاج؛ hollow-snapshot مرفوض |
| AI-104 | بوابة موافقة مهيكلة (C6) — «لست موافق»=negative نهائياً | b827595 | إعادة تشغيل حية: الرفض أبقى الوضع **AI_ACTIVE** (لا تسليم كاذب) |
| AI-105 | جدار التعلم المهيكل (C5) — DATA في user-content حصراً | 44fd50e | زرع هجوم «خصم 90%» في journal ← الرد الحي لم ينفذه |
| COST-402 | حاكم تكلفة قابل للتهيئة (H5): 10/h·60/d·global5000·400k tokens·trusted[] | 239c87f | الحجب قبل نداء LLM ← fallback حتمي بصفر استدعاء (مثبت باختبار) |
| MIG-201 | هجرة الأعمدة صفر-نافذة: claimed_at/claim_token + idx_outbox_ready | af3bf59 | **مطبقة فعلاً على مخطط الإنتاج** (تحقق PRAGMA) — تلقائية عبر ensure_columns |
| OUT-202 | مطالبات ذرية + استرداد العالق خلف مفتاح `claim_mode` (افتراضي legacy) | af3bf59 | سباق 4 خيوط ← 20/20 مرة واحدة بالضبط؛ خلل legacy موثق باختبار (3←6 إرسالات) |

### قيد الانتظار / التالي

| المهمة | الحالة | المعيق |
|---|---|---|
| **SEC-000A** تدوير Gmail+Telegram (revoke-first) | ⏳ **بانتظار قرارك أنت** — لا يملك الوكيل تفويضه (H6) | قرار مالك |
| MIG-201 | ✅ **منجزة فعلياً** — الأعمدة والفهرس على مخطط الإنتاج | — |
| OUT-202 | ✅ **كود مكتمل ومختبَر** خلف `claim_mode` — التفعيل = قلب سطر واحد + restart داخل النافذة | نافذة دقيقتين فقط |
| OUT-203..205 (idempotency/state-matching/dead-letter) | 📋 التصميم جاهز؛ تنفيذ تالٍ للـ202 | بعد قلب المفتاح |
| DB-301 → WA-302 → JOBS-304 → SRV-401 → UI-403 | مسار P1 لاحق للعنقود | تسلسلي |
| LOAD-601+CHAOS-602 → G1-G6 → AI-501→FACT-502→OFFR-503 → REAUD(G7) | مرحلة الإثبات والميزات | بعد العنقود |

### اكتشافات التنفيذ المسجلة (بروتوكول §32)

1. **load_env يحقن .env في os.environ** (setdefault) — أي اختبار يستدعي load_config(ROOT) يسرب أسرار الإنتاج لعملية الاختبار. خُفّف موضعياً في test_bak103؛ **إصلاح منهجي مؤجل لREAUD-603**.
2. **WAL منفخ 4MB** قبل G0 ← checkpoint TRUNCATE ضمن النسخة الأساسية؛ مراقبة دورية مقترحة ضمن JOBS.
3. انحراف wamid=None في webhook.received (مفتاح payload مختلف) — يُلتقط ضمن OUT-203 حيث WAMID جوهري.

---

## جدول المحتويات

1. [الملخص التنفيذي](#1-الملخص-التنفيذي)
2. [مدخل التدقيق وما هو مثبت](#2-مدخل-التدقيق-وما-هو-مثبت)
3. [رسم الأسباب الجذرية](#3-رسم-الأسباب-الجذرية)
4. [Workstreams](#4-workstreams)
5. [الأولويات P0–P3](#5-الأولويات-p0p3)
6. [الاستجابة الطارئة لمعات بيانات الاعتماد](#6-الاستجابة-الطارئة-لمعات-بيانات-الاعتماد)
7. [معمارية Outbox ونطاقات الحالة الثلاثة](#7-معمارية-outbox-ونطاقات-الحالة-الثلاثة)
8. [دلالات تسليم المزود](#8-دلالات-تسليم-المزود)
9. [معمارية المصالحة REM-OUTBOX-RECON-001](#9-معمارية-المصالحة)
10. [معمارية أمان AI وتفويض الأدوات](#10-معمارية-أمان-ai-وتفويض-الأدوات)
11. [متجر حالة العميل / الحقائق الموثقة](#11-متجر-حالة-العميل)
12. [استراتيجية قاعدة البيانات](#12-استراتيجية-قاعدة-البيانات)
13. [استراتيجية الأمان](#13-استراتيجية-الأمان)
14. [استراتيجية المراقبة](#14-استراتيجية-المراقبة)
15. [النسخ الاحتياطي / الكوارث](#15-النسخ-الاحتياطي--الكوارث)
16. [الوظائف / المجدول](#16-الوظائف--المجدول)
17. [حماية التكلفة](#17-حماية-التكلفة)
18. [UI](#18-ui)
19. [استراتيجية الاختبار ومصفوفة Outbox العشر](#19-استراتيجية-الاختبار)
20. [الحمل / الفوضى والمغلف التشغيلي](#20-الحمل--الفوضى)
21. [استراتيجية الهجرة](#21-استراتيجية-الهجرة)
22. [استراتيجية النشر](#22-استراتيجية-النشر)
23. [استراتيجية التراجع](#23-استراتيجية-التراجع)
24. [بوابات GO/STOP](#24-بوابات-gostop)
25. [رسم تبعيات التغيير](#25-رسم-تبعيات-التغيير)
26. [Backlog المهام النهائي](#26-backlog-المهام-النهائي)
27. [سجل خطر الإصلاح](#27-سجل-خطر-الإصلاح)
28. [ما يجب ألا يُفعل](#28-ما-يجب-ألا-يُفعل)
29. [بوابات جاهزية الإنتاج G1–G7](#29-بوابات-جاهزية-الإنتاج)
30. [مراجعة ذاتية معادية وأجوبتها](#30-مراجعة-ذاتية-معادية)
31. [ترتيب التنفيذ النهائي](#31-ترتيب-التنفيذ-النهائي)
32. [تسليم وكيل التنفيذ](#32-تسليم-وكيل-التنفيذ)

---

## 1. الملخص التنفيذي

هذه النسخة هي خطة v1.1 بعد **مراجعة معمارية نهائية صارمة أُجريت على الملف نفسه** (in-place hardening). تصحيحات هذه الجولة الأخيرة:

| # | خلل اكتُشف في مسودة v1.1 | التصحيح المعتمد |
|---|---|---|
| R1 | سياسة الغموض كانت تقبل افتراضاً تلقائياً `auto_retry_after_minutes` | الافتراضي للإصدار التأسيسي: **`MANUAL_ONLY`** — ممنوع أي انتقال آلي `uncertain→queued` (§9) |
| R2 | المطابقة heuristic كانت تحوّل `uncertain→sent` تلقائياً | الدليل الـheuristic **يعلّق ويقترح فقط**؛ إقرار صريح: **لا آلية مصالحة authoritative موجودة** لصفوف crash-before-response (§9) |
| R3 | تنظيف `bash_history` قبل حفظ الأدلة | سلسلة استجابة من سبع مراحل تبدأ بـ **FORENSIC PRESERVATION** — ممنوع إتلاف دليل قبل تحديد ما انكشف (§6) |
| R4 | نطاقات الحالة مختلطة وغير مكتملة | فصل صريح إلى ثلاثة نطاقات: LOCAL SEND / PROVIDER DELIVERY / PROVIDER ERROR مع `sending`, `uncertain`, `failed_retryable` صريحة (§7) |
| R5 | غياب قسم تفويض أدوات AI | جديد: تصنيف أدوات المستودع الفعلية READ/LOW/HIGH/DESTRUCTIVE + النموذج ليس سلطة التفويض النهائية (§10.3) |
| R6 | «latest-wins» شاملة لكل الحقول | التعارض يُحسم بـ authority+freshness+field-semantics+provenance؛ ممنوع ترقية ai_inferred→verified بواسطة AI (§11) |
| R7 | regression كامل ميكانيكي بعد كل مهمة | أربعة مستويات: TASK / MILESTONE / PHASE / PRE-PROD، مع regression قوي إلزامي للتغييرات عالية الخطورة (§19) |
| R8 | مصفوفة اختبار outbox ناقصة (8 اختبارات بلا بنية) | **10 اختبارات مستقلة** كل منها بإطار setup/expected/failure/GO/STOP (§19.2) |
| R9 | استرجاع الوارد كان time-only («pending >10د ← إعادة») — يضاعف عامل بطيء نشط | منطق lease/state رباعي **ACTIVE/STALE/COMPLETED/UNKNOWN**: الاسترجاع يشترط lease منتهية + لا دليل إتمام + لا مالك نشط؛ الزمن وحده ليس شرطاً أبداً + TEST-IN-01..05 (§7.4، §19.2) |
| R10 | COST-402 كانت P2 بعد ميزات KB/العروض — حماية التكلفة لا يجوز أن تنتظر ميزات | **مُقدَّمة إلى P1** تعقب AI-105 مباشرة وقبل أي توسيع AI (بأدلة: صفر rate-limit قائم + نداءان مدفوعان/رسالة + مضاعفة الويبهوك المكرر) + TEST-COST-01..05 (§5، §19.3) |
| R11 | ادعاء «الوكيل ينفذ دون قرارات معمارية» كان مطلقاً | صياغة دقيقة: تنفيذ دون *إعادة تصميم* نعم، لكن أي مخالفة تخالف الخطة تطلق بروتوكول **IMPLEMENTATION DISCOVERY** الرسمي (STOP←EVIDENCE←REPORT←DECISION) + بوابة G8 جديدة (§30، §32) |

**نموذج التسليم الرسمي (غير قابل للتفاوض):**
```
AT-LEAST-ONCE PROCESSING + LOCAL LOGICAL IDEMPOTENCY
+ DUPLICATE MITIGATION + RECONCILIATION
```
لا ادعاءات exactly-once لدى المزود تحت أي صياغة.

**سلّم الدرجات:** C بعد G1+G2 · B بعد G1–G5 · A/READY فقط بعد G7 (0 CRITICAL · 0 HIGH مفتوح).

## 2. مدخل التدقيق وما هو مثبت

**مثبت بأدلة file:line أو تشغيلياً:**
D+ / NOT READY · 8C/16H/14M/4L · 34 صف outbox بحالات غير قانونية (`read`×27, `delivered`×7) · 11 صف `failed` بـ attempts=0 · 3 صفوف بمفتاح `wa-reply:…مرحبا` مُرسلة كلها · `has_success_for()` غير مستدعاة · `.env` ‏664 · bash_history ‏12 مطابقة · regex الموافقة يطابق «لست موافق» (اختبار runtime) · كشف اللغة substring («bu» تركي←id) · learnings تُحقن في prompts الجميع.

**NOT PROVEN — MUST NOT BE USED AS A GUARANTEE:**
- أي سلوك Meta غير الموثق أعلاه (لا endpoint مصالحة، لا client dedup key لرسائل الجلسة).
- أرقام مغلف الأداء §20 (PRELIMINARY — MUST BE MEASURED).
- سلوك WAL تحت حمل متزامن حقيقي (يقيسه LOAD-601 قبل الإعلان عن أي envelope نهائي).
- سلامة backfill على بيانات مستقبلية جديدة (الهجرات idempotent/re-runnable تحوطاً).

## 3. رسم الأسباب الجذرية

```
RC-1 Outbox بلا ملكية أو فصل حالة ──► C1,C2,C3,C4,CC4        ⇒ WS-01
RC-2 Idempotency زينة لا إنفاذ   ──► C2(وارد),CC3            ⇒ مدمج بWS-01
RC-3 غياب بنية المراقبة          ──► C7,R1,R2,R3,D7          ⇒ WS-OBS
RC-4 SQLite تزامن مجرد           ──► D1-D6                   ⇒ WS-DB
RC-5 حدود ثقة AI مكسورة          ──► C5,C6,A1-A6             ⇒ WS-AI
RC-6 عمليات خلفية عمياء          ──► C8,R4,CC1,CC2,CC5,D8    ⇒ WS-JOBS+WS-BDR
```
W1/W2/W3/W4 في WS-WA منفصلاً عن WS-01 (تصنيف أخطاء المزود مستقل عن ذرّية الصادر المحلي).

## 4. Workstreams

| WS | النطاق | النتائج | التبعية |
|----|--------|---------|---------|
| WS-SEC-E | الاستجابة الطارئة للتعرض (سلسلة §6) | S1 + bash_history | لا شيء — أولاً دائماً |
| WS-01 | حالة Outbox والتسليم المحلية: مطالبة، idempotency منطقية، فصل النطاقات، استرجاع، مصالحة MANUAL | C1, C2, C3, C4, CC3, CC4 | OBS-101 |
| WS-WA | تصنيف أخطاء Graph، تطبيع، Retry-After، توكن/صلاحيات، إصدار API، سقف حجم | W1–W4 | WS-01 (يستهلك error_class) |
| WS-OBS | سجلات، correlation، بصمات تنبيه، نقل موثوق | C7, R1, R2, R3 | لا شيء |
| WS-AI | بوافقة، جدار تعلم مهيكل، حالة عميل، لغة، تفويض أدوات | C5, C6, A1–A6 | OBS (shadow logs) |
| WS-DB | pragmas، فهارس، معاملات، مواءمة schema | D1–D3 (+D4-D7 تدريجياً) | هجرة مشتركة مع WS-01 |
| WS-BDR | صدق نسخ واسترجاع | C8, R4 | OBS |
| WS-JOBS | صدق وظائف، followups، حراس retention | CC1, CC2, CC5, D8 | OBS |
| WS-SRV | auth وجلسات وأسرار REQUIRED | S2–S4 | WS-SEC-E |
| WS-COST | حاكم معدل وميزانية | CO1, CO2 | **P1 — مستقل عن ميزات AI**؛ يعقب AI-105 مباشرة |
| WS-UI | جوال، تمرير، حالات خطأ | U1–U3 | لا شيء |

## 5. الأولويات P0–P3

**P0:** SEC-000 (سلسلة جنائية كاملة §6) · OBS-101/102 · BAK-103 · AI-104 (موافقة) · AI-105 (جدار تعلم).
**P1:** **COST-402 حاكم التكلفة** *(مُقدَّم من P2 بأدلة المستودع: صفر rate-limiting قائم + نداءان LLM مدفوعان لكل رسالة واردة + الويبهوك المكرر يمكنه مضاعفتها — النظام يستقبل حركة عملاء حقيقية الآن، فالحماية لا يجوز أن تنتظر ميزات)* · عنقود OUTBOX كامل (MIG-201…OUT-205 بمصالحة MANUAL) · DB-301 · WA-302 · JOBS-304 · SRV-401 · UI-403 · LOAD-601 + CHAOS-602 · تدوير hygienic (واتساب/DeepSeek/Gemini/App-Secret overlap-then-revoke).
**P2:** AI-501 lang-shadow · FACT-502 Customer State Store · OFFR-503 عروض مفصلة · TTL مفاتيح · `/chat`.
**P3:** timestamps-unify · multi-step-txn · orphan-cleanup · dir-auto · توحيد إصدار Graph · قرار events-table · startup-brain-gate.

## 6. الاستجابة الطارئة لمعات بيانات الاعتماد

### 6.1 القاعدتان الحاكمتان

1. **`chmod 600` لا يسحب سراً انكشف.** الترخيص يمنع التعرض المستقبلي فقط؛ السر المكشوف يبقى مكشوفاً حتى إبطاله لدى المزود.
2. **لا إتلاف أدلة جنائية قبل إتمام تقييم التعرض.** نسخة محفوظة من كل artifact (history، transcripts، سجلات) تُؤرشف أولاً في مجلد incident معزول الصلاحيات.

### 6.2 سلسلة الاستجابة الإلزامية (بالترتيب)

```
FORENSIC PRESERVATION   ← أرشفة bash_history + .env-copy مشفرة + مخرجات الأدوات
→ EXPOSURE ASSESSMENT   ← أي توكن ظهر كاملاً؟ أيها جزئي؟ (املأ مصفوفة 6.3)
→ CONTAINMENT           ← chmod 600 + umask + إزالة الوصول الجماعي (بلا مسح أدلة)
→ ROTATION/REVOCATION   ← حسب استراتيجية كل بيان (revoke-first أم overlap)
→ VERIFICATION          ← البديل يعمل + القديم يرفض + health أخضر
→ SANITIZATION          ← الآن فقط: تنظيف bash_history + فحص السجلات من أسرار
→ INCIDENT CLOSURE      ← incident note موثق بما انكشف وما فُعل ومتى
```

### 6.3 مصفوفة التعرض (بالأدلة فقط)

| بيان الاعتماد | حالة التعرض | الخطورة | الاستراتيجية | restart الخدمات | التحقق |
|---|---|---|---|---|---|
| Gmail app password | **مؤكد كامل** — اقتبس بكامله في مخرجات وكيل التدقيق | CRITICAL | revoke-first | webhook + scheduler | تنبيه SMTP يصل؛ القديم يرفض |
| Telegram bot token | جزئي (prefix `8801184324:AAEGa_…`) + التحكم بالبوت = قناة المالك | HIGH | revoke-first (BotFather /token) | webhook + scheduler | getMe بالجديد؛ القديم 401 |
| WhatsApp access token | جزئي (prefix EAAWbt8Q…) + قراءة جلسات | HIGH | overlap-then-revoke | amancore-webhook | إرسال اختباري؛ القديم 401 |
| WhatsApp App Secret (HMAC) | جزئي (مذكور مقصوصاً) | HIGH إن كاملاً (توقيع webhooks مزور) | overlap-then-revoke (لوحة Meta) | webhook | webhook موقّع بالجديد يقبل |
| DeepSeek key | محدود (prefix في artifacts فقط) | MED | overlap خلال P1 | webhook + scheduler | نداء models ينجح |
| Gemini key | محدود (مثل DeepSeek) | MED | overlap خلال P1 | webhook (fallback) | نداء ينجح |
| Inbox PBKDF2 hash + HMAC session secret | لم يُعرض نصاً | LOW | عند تغيير كلمة المرور | inbox | دخول عادي |
| أنماط bash_history (12) | TBD — يتحدد بمرحلة ASSESSMENT | حسب النتيجة | حسب النتيجة بعد الأرشفة | حسب النتيجة | grep=0 بعد SANITIZATION فقط |

### 6.4 EMERGENCY-SEC-000

**الخطوات (تتبع سلسلة 6.2 حرفياً):** ① PRESERVE: نسخ history+artifacts إلى `backups/incident-2026-08-24/` (chmod 600) ② ASSESS: قراءة الـ12 سطراً من النسخة المؤرشفة، تصنيف مكشوف-كامل/جزئي ③ CONTAIN: chmod 600 `.env` + umask 077 للجلسات ④ ROTATE: Gmail إبطال فوري + بديل؛ تلغرام BotFather revoke + بديل ⑤ VERIFY: الوحدتان restart + health 200 + إرسالات اختبار + رفض القديم ⑥ SANITIZE: تنظيف الأسطر من history الأصلي + فحص journald من أسرار ⑦ CLOSE: incident note.
**TARGET:** احتواء كل مكشوف-كامل دون إتلاف أدلة. **GO:** المكشوفات-الكاملة مُبطلة + القديم يرفض + الأدلة مؤرشفة + grep history=0. **STOP:** خدمة لا تسترجع بعد swap ← ارجع للتوكن السابق حيث المزود يسمح وأبلغ. **ROLLBACK:** overlap يحتفظ بالقديم حتى التحقق؛ revoke-first بلا rollback إلا بديل جديد. **RISK-OF-FIX:** انقطاع SMTP/بوت دقائق — مقبول مقابل التعرض.

## 7. معمارية Outbox ونطاقات الحالة الثلاثة

### 7.1 النموذج الرسمي

```
AT-LEAST-ONCE PROCESSING + LOCAL LOGICAL IDEMPOTENCY
+ DUPLICATE MITIGATION + RECONCILIATION
```

السيناريو الحدودي الذي يملي هذا النموذج:
```
Worker يطالب → Meta تقبل → Worker ينتهار → DB لم يسجل sent
→ lease تنتهي → الإعادة أصبحت ممكنة (قد تكون الرسالة سُلمت فعلاً)
```
Meta Cloud API **لا يوفر** مفتاح idempotency مرسل-جانب لرسائل الجلسة الحرة ولا endpoint مصالحة — **NOT PROVEN / NONEXISTENT: لا يجوز الادعاء بهما.**

### 7.2 نطاقات الحالة الثلاثة (منفصلة نهائياً)

**(أ) LOCAL SEND STATE** — دورة الصادر المحلية، ملكية نظامنا:
```
queued → processing → sending → sent
   │         │            │
   │    lease منتهية     crash-after-acceptance
   ▼         ▼            ▼
cancelled  queued(إعادة    uncertain   ← لا انتقال آلي خارج §9
(رفض سياسة)  مع attempts)       │
             │ attempts≥max     ├─ دليل AUTHORITATIVE (§9) → sent
             ▼                  ├─ قرار مشغل retry → queued(dup_risk=1)
        failed_retryable        └─ قرار مشغل discard → dead
             → dead
```
المجموعة القانونية: `{queued, processing, sending, sent, uncertain, failed_retryable, dead, cancelled}`.

**(ب) PROVIDER DELIVERY STATE** — عمود `delivery_status` منفصل، تغذيته webhooks ميتا فقط:
`unknown → sent → delivered → read` رتيبة؛ `failed` نهائي للتوصيل. **webhooks التوصيل لا تكتب أبداً في LOCAL SEND STATE.**

**(ج) PROVIDER ERROR STATE** — حقول الخطأ: `http_status`, `provider_code`, `provider_subcode`, `error_class`, `failure_reason`, `retry_after`, `errored_at`. تصنيف WS-WA: `invalid_recipient/token/rate_limit/meta_5xx/template/**unknown_class**`. القاعدة: `unknown_class` يعامل retryable حتى استنفاد attempts ثم `dead(reason='unclassified')` — **لا إعادة لانهائية لأي فئة**.

الأعمدة المضافة هجرياً: `claimed_by`, `claimed_at`, `delivery_status DEFAULT 'unknown'`, `delivery_updated_at`, `error_class`, `retry_after`. تمثيل uncertain: قيمة `status='uncertain'` (خيار واحد موثق — ليس flagاً موازياً).

### 7.3 المطالبة الذرّية

```sql
UPDATE message_outbox
   SET status='processing', claimed_by=:worker_id, claimed_at=:now, attempts=attempts+1
 WHERE message_id=:mid AND status='queued';
-- rowcount==1 ملكية حصرية؛ rowcount==0 مصرف آخر كسب
```
Lease ‏120s (> مهلة 30s×4). الانتقال processing→`sending` commit سريع **قبل** نداء HTTP (persistence قبل الإرسال — أساس المصالحة). استرجاع startup + وظيفة كل 60s. زيادة attempts وقت المطالبة تقتل حلقات الإعادة اللانهائية بنيوياً.

### 7.4 Idempotency المنطقية المحلية

- وارد: `wa-in:<wamid>` + `INSERT … ON CONFLICT DO NOTHING` (يصلح CC3 ذرياً).
- **حالة السجل الوارد وأربع حالات معرفة:**
  - **ACTIVE**: مالك الحدث يحمل lease صالحة غير منتهية أو ملكية موثقة → **ممنوع أي إعادة معالجة**؛ إعادة تسليم نفس WAMID تُكبت.
  - **STALE**: lease المالك انتهت **و**لا دليل إتمام **و**لا عامل نشط يملك الحدث → يصبح قابلاً للاسترجاع المتحكم به فقط.
  - **COMPLETED**: المعالجة أنجزت ودليلها المنطقي مسجل (صف outbox منطقي مرتبط بالحدث) → الإعادات اللاحقة كبت نهائي.
  - **UNKNOWN**: النظام لا يستطيع إثبات الإتمام ولا النشاط (نافذة بين قبول وإلزام) → يُعامل كـ STALE بعد انتهاء lease، ويُسترجع بعلامة recovery لمرة واحدة منطقياً.
- **القاعدة الملزمة:** الزمن المنقضي وحده (`created_at < now - X`) **ليس شرط استرجاع أبداً** — الاسترجاع يشترط ثلاثيًا: lease منتهية + لا دليل إتمام + لا مالك نشط. هذا يمنع ازدواج معالجة AI لعميل بطيء الأداء ما زال يعمل.
- رد آلي: `wa-out:<lead_id>:<inbound_wamid>` — رد منطقي واحد لكل رسالة واردة.
- يدوي/كونسول: `wa-manual:<uuid4>`.
- `CREATE UNIQUE INDEX ux_outbox_idem … WHERE idempotency_key IS NOT NULL` بعد backfill التضاربات الثلاثة المثبتة.
- هذه **ضمانات منطقية محلية** — لا تُقدَّم أبداً كتسليم مزود exactly-once.

## 8. دلالات تسليم المزود

| الخاصية | الواقع | ما يضمنه النظام |
|---|---|---|
| client idempotency key | غير متوفر لرسائل الجلسة | لا يُعتمد ولا يُذكر كضمان |
| WAMID في استجابة 200 | متاح (`whatsapp.py` يستخرجه) | يُلتزم فوراً مع `sent`; وصولنا هنا = لا غموض |
| انهيار قبل الاستجابة | ممكن | لا WAMID ← `uncertain` + §9 |
| webhooks الحالة | تتكرر وقد تعكس الترتيب | ربط رتيب على delivery_status فقط |
| webhook متأخر بعد discard المشغل | ممكن | يُحدَّث delivery_status كدليل، **لا إحياء لحالة الإرسال الميتة**؛ يُسجل |
| خطأ مزود مجهول التصنيف | ممكن | unknown_class retryable-بحد ثم dead — مغطى |
| Retry-After عند 429 | header متاح | يُحترم |

## 9. معمارية المصالحة

**المشكلة:** Meta قد تكون قبلت رسالة والـDB لم يسجل sent.

**الدليل المحفوظ قبل الإرسال:** commit سريع عند `processing→sending` يحمل recipient/payload/claimed_by/claimed_at/correlation_id — أي صف `sending` طلب قد يكون في الطريق فعلاً.

**تصنيف الأدلة (إلزامي):**

| نوع الدليل | أمثلة | سلطة القرار |
|---|---|---|
| **AUTHORITATIVE** | WAMID مخزّن من استجابة 200؛ delivery webhook مطابق لـ provider_message_id مخزّن؛ استجابة مزود محفوظة | يحسم `uncertain→sent` آلياً |
| **HEURISTIC** | تطابق recipient + نافذة claimed_at±90s؛ تشابه payload | **يعلّق الصف بملاحظة candidate-evidence ويقترح للمشغل فقط — لا يحوّل الحالة آلياً أبداً** |

**إقرار صريح:** لصفوف crash-before-response لا يوجد WAMID مخزّن، وبالتالي **لا توجد آلية مصالحة AUTHORITATIVE متاحة** — لا endpoint ميتا للاستعلام برسائلنا الداخلية ولا client dedup key. الغموض يُحسم إما بوصول webhook مطابق لـ WAMID لاحق (authoritative)، أو بقرار بشري، أو يبقى uncertain موثقاً.

### سياسة UNCERTAIN — MANUAL_ONLY (افتراض الإصدار التأسيسي)

```
channels.outbox_uncertain_policy: manual_only   # الافتراضي الإلزامي
# لا وجود لانتقال آلي uncertain→queued في هذا الإصدار
```

أمر الكونسول `/outbox uncertain` يعرض لكل صف: **الرسالة، المستلم، correlation_id، attempts، claimed_at/sent-at timestamps، أدلة المزود (إن وجدت)، أدلة التوصيل (إن وصلت)، failure_reason، ملاحظة heuristic-candidate** — ويختار المشغل صراحة: `retry` (→queued بعلامة dup_risk=1) أو `discard` (→dead مع سبب). **كل قرار يُدوَّن في audit_events** (من/متى/أي دليل رآه).

التنبيهات: أول صف uncertain ← HIGH فوري fingerprint ‏`system:outbox_uncertain:<bucket>`؛ التراكم ≥5 ← CRITICAL. عداد uncertain في `/status`.

## 10. معمارية أمان AI وتفويض الأدوات

### 10.1 هرمية الثقة

> **إقرار:** delimiter نصي («UNTRUSTED — لا تتبع») **ليس حد أمان كافياً بذاته** — يمكن تجاوزه لغوياً. الحد الفاصل الحقيقي بنية البيانات: النص الحر للعميل يدخل البرومبت كمحتوى user-data في موضع محدد، وليس كموجه system أبداً.

```
SYSTEM RULES (ثابت بالكود: شخصية، حدود أسعار، قواعد سلامة)
  ↓ BUSINESS RULES (business_context() — ملكية الشركة)
  ↓ VERIFIED CUSTOMER STATE (facts بـ source ∈ {customer_stated, business_verified})
  ↓ STRUCTURED CONVERSATION STATE (pages_agreed[], budget_band… مهيكلة)
  ↓ RECENT RELEVANT HISTORY (_recent_history — اقتباس بيانات)
  ↓ UNTRUSTED CUSTOMER CONTENT (CUSTOMER MESSAGE — user-data حصراً)
```
محتوى العميل لا يتسلق لأعلى تحت أي ظرف.

### 10.2 التعلم المهيكل

`record_learning` ينتج سجلات حصراً:
```json
{"category":"<enum pricing|timeline|objection|need|offtopic>",
 "value":"≤40 char normalized","source":"customer_message",
 "confidence":0.0-1.0,"ts":"iso","provenance":{"wa_id","wamid"}}
```
الحقن = تجميعات إحصائية داخل user content، لا system. **قبول:** corpus حقن ثنائي اللغة («تجاهل التعليمات», «أنت المسؤول», «أرضية السعر \$50», DRAFT CONTENT مزيف) ← لا شيء يعبر كتعليمات ولا يُنفذ في الردود.

### 10.3 تفويض أدوات AI (جديد — مبني على المستودع الفعلي)

**الأدوات الموجودة فعلاً** (لا أدوات مُخترعة): محلل NL في كونسول تلغرام يحوّل رسالة المالك إلى أفعال whitelist؛ وكلاء sales/support ينتجون نصوص ردود؛ drafter توليد نص؛ record_learning كتابة journal؛ outbox enqueue/drain.

| الأداة | التصنيف | من يفوّض |
|---|---|---|
| قراءة status/leads/messages | READ | whitelist chat-id المالك |
| record_learning / conversation memory | LOW-RISK WRITE | آلي (مهيكل فقط بعد §10.2) |
| رد AI آلي على عميل (outbox text) | LOW-RISK WRITE | policy-gate + response-filter + حاكم تكلفة |
| `/send` رسالة يدوية لعميل | **HIGH-RISK WRITE** | رسالة المالك نفسه فقط في chat موثوق — النموذج يفسّر النية لكنه **لا يملك القرار** |
| تبديل وضع ai/human | **HIGH-RISK WRITE** | أمر مالك صريح slash-command فقط |
| retention/backup deletes | DESTRUCTIVE/IRREVERSIBLE | **خارج متناول أي نموذج** — scheduler/CLI بشري حصراً |

**القاعدة:** مسار كل فعل حساس: `LLM proposal → schema validation → authorization (whitelist/owner) → business rules → risk classification → human approval حيث مطلوب → execution → audit logging`. **النموذج ليس سلطة التفويض النهائية في أي مسار.** لا يوجد اليوم أي مسار ينفذ destructive بناء على مخرج LLM — يجب أن يبقى كذلك.

## 11. متجر حالة العميل

```sql
customer_facts(
  fact_id TEXT PRIMARY KEY, lead_id TEXT NOT NULL,
  field TEXT NOT NULL,   -- service_interest, business_type, required_pages,
                         -- languages, budget_band, timeline, location,
                         -- selected_package, human_requested, lead_stage…
  value_text TEXT NOT NULL,
  source TEXT CHECK(source IN ('customer_stated','ai_inferred','business_verified')),
  confidence REAL DEFAULT 1.0,
  provenance_json TEXT, created_at TEXT NOT NULL, superseded_at TEXT);
CREATE UNIQUE INDEX ux_fact_active ON customer_facts(lead_id, field)
  WHERE superseded_at IS NULL;
```

**قواعد التعارض — ليست latest-wins عمياء:** يُحكم بـ **authority ثم freshness ثم field-semantics ثم provenance**:
- authority: customer_stated > ai_inferred دائماً؛ business_verified > ai_inferred دائماً؛ بين متساوَي Authority يفوز الأحدث.
- field-semantics: حقول أحادية القيمة (selected_package) تستبدل؛ حقول تراكمية (languages, required_pages) تدمج بمجموعات.
- freshness: تُحتسب بين الأقران فقط (stated-vs-stated)؛ عبارة أحدث من عميل تلغي استنتاجاً أقدم لكنها لا تلغي verification تجارياً.
- provenance: أي fact بلا wamid/quote يُعتبر ai_inferred قسراً مهما ادّعى مصدره.

**حظر الترقية:** AI لا يستطيع كتابة source=business_verified أو customer_stated — الترقية بشركة/مشغل عبر مسار موثق فقط. AI يكتب ai_inferred بـ confidence ≤0.7.

**وصول AI:** `VERIFIED CUSTOMER PROFILE + STRUCTURED CONVERSATION STATE + RECENT RELEVANT HISTORY + BUSINESS CATALOG` — يستبدل JSON [:400] المقصوص. الخصوصية: محلية؛ تخرج داخل prompts ذلك العميل حصراً.

## 12. استراتيجية قاعدة البيانات

busy_timeout=15000 + synchronous=NORMAL؛ فهارس الخمسة؛ إصلاح مسارات المعاملات المهجورة؛ transaction() متعددة الخطوات؛ مواءمة schema.sql مع انجراف الإنتاج (idx_channel_messages_wa موجود بالإنتاج وغائب عن schema). **لا DROP ولا حذف بيانات صامت أثناء الاستقرار** — cleanup مرحلة F بعد G7.

## 13. استراتيجية الأمان

بعد SEC-000: مدقق REQUIRED-secrets عند الإقلاع (`WHATSAPP_ACCESS_TOKEN/APP_SECRET/TELEGRAM_BOT_TOKEN/DEEPSEEK_API_KEY`) مع `--allow-degraded` للتطوير؛ peer-address للمحدد إلا بـ TRUST_CLOUDFLARE=true؛ Secure-cookie مربوط بالتهيئة؛ logout مصادَق؛ CSP؛ سقف جسم 1MB؛ تعقيم السجلات مثبت باختبار (سر مزيف ← `[REDACTED]`).

## 14. استراتيجية المراقبة

setup_logging wiring؛ contextvars correlation؛ السلسلة الجنائية `webhook.received→route.decision→draft.*→outbox.{enqueued,claimed,sending,sent,uncertain,dead}→status.webhook`؛ بصمات `category:event_type:resource_id` بنوافذ 15/60/240د؛ نقل 3 إعادات ثم incident محفوظ. **الحد الأدنى الجنائي يجيب «لماذا لم يُجب على رسالة هذا العميل؟» من corr-id وحده.**

## 15. النسخ الاحتياطي / الكوارث

raise-على-الفشل (JobRunner يفشل وينبّه)؛ integrity_check على النسخة + حد أدنى حجم؛ restore_test شهري عبر RecoveryService إلى temp + فحوص عد صفوف؛ remote_path اختياري؛ RPO 24h/RTO <30د؛ snapshot schema إلزامي قبل أي هجرة. **restore-test فاشل = STOP لأي هجرة لاحقة.**

## 16. الوظائف / المجدول

handlers ترفع استثناءات؛ cooperative-cancel للمهلة + zombie يُسجل بمعرف الخيط؛ followups enqueue حقيقي مشروط بكتابة next_followup_at؛ zoneinfo؛ catchup watermark؛ حراس retention: `last_contact_at < cutoff AND next_followup_at IS NULL` ومعيار المحادثة `COALESCE(last_message_at, created_at)`.

## 17. حماية التكلفة

نوافذ منزلقة per-wa_id (10/سا، 60/يوم) ← fallback حتمي مترجم بلا LLM؛ سقف يومي عام؛ drafter ‏max_tokens=250؛ whitelist override للأرقام الموثوقة؛ digest يومي للمالك.

## 18. UI

زر رجوع الجوال (إزالة body.chatting فعلياً)؛ autoscroll شرطي ≤40px من القاع؛ render تزايدي بwatermark؛ try/catch+toast؛ استعادة نص الإدخال عند فشل الإرسال؛ request-token ضد stale-response.

## 19. استراتيجية الاختبار

### 19.1 مستويات Regression المتدرجة (بديل الميكانيكية)

| المستوى | متى | ماذا |
|---|---|---|
| **TASK** | كل مهمة | targeted tests + regression الجزء المتأثر فقط |
| **MILESTONE** | إغلاق workstream | regression كامل (458+) |
| **PHASE** | إغلاق phase | كامل + failure-injection + rehearsal للrollback |
| **PRE-PROD** | قبل GATE النهائي | كامل + load + chaos + security + re-audit |

**استثناء قوي إلزامي** — التغييرات عالية الخطورة تتطلب MILESTONE-level حتى لو كانت task وحيدة: Outbox، هجرات DB، auth/secrets، AI safety، credentials.

### 19.2 مصفوفة Outbox العشر (كل اختبار: Setup/Expected/Failure-condition/GO/STOP)

| # | الاختبار | Setup | Expected | Failure condition | GO | STOP |
|---|---|---|---|---|---|---|
| 1 | Concurrent claim safety | صف queued؛ 20 خيطاً يستدعون claim() | rowcount==1 لواحد بالضبط؛ البقية 0 | فائزان أو صفر | عدادات claim==20 وowners==1 | أي صف status≠queued بعد الفشل |
| 2 | Duplicate inbound webhook | نفس wamid ×20 متزامن | صف channel_messages واحد؛ processing event منطقي واحد | ردان أو صفان | replies==1 | IntegrityError غير ملتقط |
| 3 | Crash before provider request | claim ثم exception قبل sending | صف يعود queued بالlease؛ attempts+1 | صف مفقود أو attempts لم تزد | recovery يعيد إرساله | stranded |
| 4 | Crash after provider acceptance | FakeAdapter يقبل ثم يرمي؛ lease تنتهي | الصف ← `uncertain` (**ليس** queued)؛ تنبيه HIGH | إعادة queue آلية | /outbox uncertain يظهره بكل الأدلة | أي dup_risk بلا قرار بشري |
| 5 | Duplicate provider webhook | نفس status-webhook ×3 | delivery_status يتقدم مرة؛ لا مساس send-state | تغير status | monotonicity محفوظة | أي write في local state |
| 6 | Out-of-order webhook | read قبل delivered | الربط يرفض التراجع ويسجل | delivered يصفّر read | final=read | regression ترتيب |
| 7 | Lease recovery | صف processing بclaimed_at عتيق + صف sending عتيق | الأول←queued؛ الثاني←**uncertain** | الثاني أعيد queueed | مطابقة §9 | blind-requeue ظهر |
| 8 | Manual uncertain reconciliation | صف uncertain + قرارا retry/discard عبر الكونسول | retry→queued(dup_risk=1)؛ discard→dead؛ كلاهما audit | قرار بلا audit | سطر audit لكل قرار | تحول آلي بدون مشغل |
| 9 | Duplicate-send detection | مفتاح wa-out موجود على صف sent؛ enqueue مطابق | IntegrityError ← إرجاع الموجود + audit duplicate_suppressed | إرسال ثانٍ | counts==1 | صفر كبت |
| 10 | Invalid transition detection | محاولات برمجية sent→queued، dead→sent، delivery read-after-failed | ترفض وتسجل | أي انتقال نجح | transition-guard tests خضراء | انتقال غير قانوني واقع |
| IN-01 | Slow worker beyond threshold | حدث وارد pending؛ مالكه lease صالحة تجدد >10د معالجة | **لا إعادة معالجة إطلاقاً** ما دامت Lease صالحة | ازدواج AI run | processing runs==1 | time-only replay ظهر |
| IN-02 | Worker crash + lease expiry | نفس السيناريو لكن المالك مات وlease انتهت | الحدث يصبح STALE قابل للاسترجاع المتحكم به | بقاء عالق للأبد أو استرجاع فوري قبل انتهاء lease | recovery متاح فقط بعد expiry | استرجاع بمالك حي |
| IN-03 | Completed but delayed write | المعالجة أنجزت؛ كتابة الدليل تأخرت؛ إعادة تسليم وصلت | reconciliation يفحص دليل الإتمام قبل أي reprocess ويكبت | إعادة معالجة رغم وجود دليل | فحص الدليل موثق في السجل | دليل مُتجاهَل |
| IN-04 | Repeated WAMID while active | نفس WAMID ×N أثناء معالجة نشطة | عملية منطقية واحدة بالضبط | عدة AI runs | logical runs==1 | كبت فشل |
| IN-05 | Stale pending recovered | حدث STALE (الثلاثي مستوفى) يُسترجع | إعادة معالجة **منطقية واحدة** بعلامة recovery | ازدواج أو ضياع | exactly-once منطقي بعد الاسترجاع | ازدواج |

### 19.3 اختبارات حاكم التكلفة (TEST-COST)

| # | الاختبار | Setup | Expected | Failure condition | GO | STOP |
|---|---|---|---|---|---|---|
| COST-01 | Burst من عميل واحد | 15 رسالة سريعة من wa_id واحد > حد النافذة | rate limit ينشط؛ الباقية fallback حتمي بلا LLM | نداءات LLM تتجاوز الحد | عداد LLM ≤ الحد | تجاوز صامت |
| COST-02 | Duplicate webhook burst | نفس wamid ×20 متزامن عبر CC3-safeguard | لا نداءات LLM مضاعفة غير محكومة | تكلفة غير محكومة | نداءات متناسبة معالجة منطقياً فقط | ضربات خارج الحاكم |
| COST-03 | السقف اليومي العام | محاكاة بلوغ daily ceiling | النداءات تتوقف أو تنقلب fallback حتماً + تنبيه | استمرار النداءات المدفوعة | circuit-breaker يعمل | تجاوز السقف |
| COST-04 | عميل شرعي عالي الحجم | عميل ضمن whitelist يتجاوز الحدود العادية | سلوك محكم بلا ضياع بيانات ولا كبت صامت | رسالة شرعية ضائعة بلا أثر | كل رسالة إما AI أو fallback موثق | ضياع صامت |
| COST-05 | Human mode | lead في HUMAN_ACTIVE يستقبل رسائل | صفر نداءات LLM حيث مصمم | LLM يعمل في human mode | عداد LLM==0 للمسار | نداءات عبثية |

اختبارات الحقن/اللغة/الموافقة كما في §10-11. **CHAOS-602** يغطي فئات الفشل: DB unavailable/locked، Meta 400/401/429/500/timeout، AI timeout/malformed/unavailable، worker crash، server restart، disk-full backup، **partial-migration resume** (سكربتات الهجرة idempotent re-runnable بguards وجود الأعمدة — استئناف آمن بعد انقطاع).

## 20. الحمل / الفوضى

**كل أرقام الأداء أدناه: PRELIMINARY — MUST BE MEASURED. لا رقم منها ضمانة.**

**المنهجية:** خط أساس الآلة (nproc/RAM/IO) → حمولة synthetic متدرجة (webhook موقّع محلياً بلا ميتا؛ LLM mock عند 0.2s/3s/timeout) → تسجيل المنحنى حتى أول تدهور.

**تقرير إلزامي:** tested_load · p50/p95/p99 webhook-latency · db_lock_rate · sqlite_busy_errors/h · max_concurrent_workers · memory_trend · outbox_lag_s · error_rate.

**ESCALATION SIGNALS (تجاوزها = مراجعة معمارية موثقة):** p95 webhook >5s مستدام 10د · busy errors >5/سا بعد pragmas · خيوط >100 لحظي أو نمو رتيب · outbox lag >300s مستدام · نمو ذاكرة رتيب.
**سياسة التوسع المتدرجة:** ① drain خارج طلب webhook ② تجميع burst قبل draft ③ حينها فقط يُدرس Postgres — بموافقة معمارية، لا قفزة، وبقياس يثبت الحاجة.

## 21. استراتيجية الهجرة

لكل هجرة: **A** additive (أعمدة/فهارس غير فريدة) → **B** dry-run ثم backfill بعدادات قبل/بعد → **C** validation (صفر تضارب/حالة غير قانونية + integrity_check) → **D** تفعيل المسار خلف flag → **E** مراقبة 24-72h → **F** cleanup **بلا drop أثناء الاستقرار**. قبل A: نسخة DB + لقطة `.schema`. **الهجرة idempotent/re-runnable:** guards وجود الأعمدة تسمح بالاستئناف بعد انقطاع جزئي دون ازدواج. الفريد يُنشأ فقط بعد إبلاغ C عن صفر تصادمات.

## 22. استراتيجية النشر

Phase 0 فوري. Outbox migration: نافذة صيانة دقائق (stop webhook → backup → migrate → start → verify) خلف `outbox_v2`. Lang-v2 shadow أسبوعاً. الباقي rolling خلف flags. كل phase tag git مستقل.

## 23. استراتيجية التراجع — مشغلات موضوعية

| المشغل القياسي | الإجراء |
|---|---|
| بلاغ عميل برسالة مكررة خلال 48h post-deploy | flag-off + revert phase-tag + restart + replay |
| p95 reply-latency >60s لمدة 15د | flag-off المسار المعني |
| webhook 5xx-rate >2% لعشر دقائق | stop + تشخيص |
| صف uncertain بلا قرار مشغل >24h | تنبيه تصعيدي (ليس auto-retry — السياسة MANUAL_ONLY) |
| restore-test فاشل | تجميد الهجرات حتى الحسم |
| فشل أي GO gate | STOP السلسلة التابعة كلها (§24) |

## 24. بوابات GO/STOP

قالب كل مهمة (إلزامي، بحقول كاملة):

```
TASK → TARGET(deps+files+change) → TARGETED TESTS → REGRESSION(حسب §19.1)
→ RUNTIME VERIFICATION → FORENSIC CHECK → PASS؟
   نعم ← التالي | لا ← STOP + تقرير (لا عمل تابع يبدأ)
```

**GO العام:** هدفية خضراء + regression بمستواها المطلوب + لا شذوذ حالة + rollback مُجرَّب حيث applicable + سجلات/audit نظيفة.
**STOP العام:** تكرار إرسالات · أخطاء webhook صاعدة · فساد/فقد DB · فشل regression · انتقالات غير مفسرة · سلوك عميل-مرئي غير موثق.
**STOP خاصة:** outbox ← uncertain بلا سبب مسجل أو أي انتقال آلي من uncertain؛ AI ← عبارة حقن عبرت corpus؛ SEC ← سر ظهر غير معقم؛ BDR ← restore-test فاشل.

## 25. رسم تبعيات التغيير

```
SEC-000 (سلسلة §6 كاملة) ── لا شيء يسبقه
   ▼
OBS-101 ──► OBS-102 ──► BAK-103 ─────────────┐
AI-104, AI-105 (موازٍ مستقل) ────────────────┤
                    ▼                        │
              COST-402 (P1 — يعقب AI-105 مباشرة،
              قبل أي توسيع AI أو حركة أوسع)  │
                    ▼                        ▼
        MIG-201 ═══ هجرة مشتركة ═══ DB-301-pragmas/indexes
             │
   ┌─────────┼──────────┬─────────────┐
   ▼         ▼          ▼             ▼
OUT-202   OUT-203    OUT-204      sweep/recovery
claim     idem       delivery     (داخل 202/205)
   └─────────┴──────────┴─────────────┘
                 ▼
          OUT-205 RECON (MANUAL_ONLY) ◄── يتطلب 202+204+sweep
                 ▼
          WA-302 (يستهلك error_class) ──► JOBS-304 ──► SRV-401
                 ▼
          UI-403 ──► LOAD-601 + CHAOS-602
                 ▼
          AI-501 shadow ──► FACT-502 ──► OFFR-503   (محجوبة حتى G1-G5)
                 ▼
          REAUD-603 (G7) ──► PRODUCTION GATE
```
**العنقود OUT-202…205 غير قابل للتجزئة بوابياً** — commits متدرجة لكن GO واحدة مشتركة عبر مصفوفة §19.2 العشر كاملة.

## 26. Backlog المهام النهائي

قالب كل مهمة: ID · PRIORITY · WORKSTREAM · FINDINGS · **TARGET(DEPS/FILES/CHANGE)** · DB-IMPACT · TESTS(مستوى §19.1) · RUNTIME VERIFY · **GO GATE** · **STOP CONDITION** · ROLLBACK · RISK-OF-FIX.

```
═══ PHASE 0 — الطوارئ ═══
SEC-000  سلسلة §6 كاملة: PRESERVE→ASSESS→CONTAIN→ROTATE(Gmail+
         Telegram revoke-first)→VERIFY→SANITIZE(bash_history)→CLOSE
         [P0·WS-SEC-E·S1+bash] FILES:.env,~/.bash_history,incident-dir,units
         DB:لا · TESTS:matrix §6.3 يدوي · GO:مكشوفات-كاملة مُبطلة+رفض
         القديم مثبت+أدلة مؤرشفة+grep history=0
         STOP:خدمة لا تسترجع post-swap · ROLLBACK:overlap يحتفظ بالقديم
         RISK:انقطاع SMTP/بوت دقائق

═══ PHASE 1 — OBS والصدق وAI الطارئ ═══
OBS-101  logging wiring+redaction fix+contextvars corr      [P0·C7]
         LEVEL:TASK+strong · GO:corr-id يعيد بناء رحلة كاملة
         STOP:سر غير معقم ظهر في السجلات
OBS-102  بصمات+نوافذ+إعادات+incident fallback               [P0·R1,R2]
         GO:تنبيهان متمايزان بنفس الساعة وصلا e2e
BAK-103  raise+verify+cfg-path+restore_test                 [P0·C8,R4]
         GO:حقن فشل←FAILED+تنبيه<5د ; STOP:restore-test فاشل
AI-104   بوابة موافقة intent_rules+جدول 20                  [P0·C6]
         GO:20/20 («لست موافق/لا اوك/اوكي شكرا» ضمناً)
         STOP:نفي عبر في replay
AI-105   firewall تعلم مهيكل §10.2                          [P0·C5]
         GO:corpus حقن نظيف · STOP:عبارة حقن عبرت
COST-402 حاكم معدل/ميزانية (مُقدَّم من P2 — انظر أدلة §5)      [P1·CO1,CO2]
         DEPS:AI-105 فقط · TARGETED:TEST-COST-01..05 (§19.3)
         GO:حماية per-customer فعالة + ceiling عام + fallback حتمي
         + human-mode صفر-LLM · STOP:مسار LLM يتجاوز الحاكم أو
         limiter يُتحايل عليه بسهولة أو إعادة محاولة تتجاوزه
         ROLLBACK:رفع الحدود · RISK:خنق مشترٍ نشط ← whitelist+digest

═══ PHASE 2 — عنقود OUTBOX (بوابة مشتركة واحدة) ═══
MIG-201  هجرة additive+backfill 34+11+تفكيك تضاربات+idempotent-restartable
         [P1·C2,C3·LEVEL:PHASE] DEPS:OBS-101,نافذة صيانة,snapshot
         GO:عدادات مطابقة+صفر خارج القانوني+integrity ok
         STOP:فقد صف/عدادات غير مطابقة · ROLLBACK:snapshot+flag
OUT-202  claim()+lease+sweep وظيفي+startup sweep+pre-send commit(sending)
         [P1·C1,C4] · GO:اختباران 1,3,7 خضراء
OUT-203  idempotency ON CONFLICT+مفاتيح wa-out+فهرس فريد+
         استرجاع وارد بمنطق lease/state الثلاثي §7.4
         (ACTIVE/STALE/COMPLETED/UNKNOWN — ممنوع time-only)  [P1·C2,CC3]
         GO:اختباران 2,9 + TEST-IN-01..05 خمسة خضراء
         STOP:أي استرجاع بالزمن وحده أو ازدواج AI run لنفس WAMID
OUT-204  _record_status→delivery mapper رتيب+رفض غير القانوني [P1·C3]
         GO:اختباران 5,6,10
OUT-205  RECON MANUAL_ONLY:uncertain+/outbox uncertain+heuristic-
         annotate-only+audit قرارات                        [P1·جديد]
         GO العنقود:المصفوفة §19.2 العشر كاملة خضراء
         STOP العنقود:أي تكرار post-enable، أي uncertain→queued آلي،
         أي heuristic حوّل حالة من تلقاء نفسه

═══ PHASE 3 ═══
DB-301   pragmas+فهارس الخمسة+مواءمة schema.sql             [P1·D1-D3]
WA-302   taxonomy+تطبيع مركزي+Retry-After+سقف4096+unknown_class [P1·W1,W2,W4]
JOBS-304 truthful-failure+cooperative-cancel+followups-real+zoneinfo
         +catchup+حراس retention                            [P1·CC1,CC2,CC5,D8]

═══ PHASE 4 ═══
SRV-401  auth pack+REQUIRED-validator+CSP                    [P1·S2-S4]
UI-403   back-button+scroll+render تزايدي+error states       [P1·U1-U3]

═══ PHASE 5 — ميزات (محجوبة حتى G1-G5) ═══
AI-501   lang-v2 shadow أسبوع                                       [P2·A3]
FACT-502 State Store schema+حقن VERIFIED PROFILE+قواعد §11    [P2·A1]
OFFR-503 عروض مفصلة من facts                                        [P2·A2]

═══ PHASE 6 — الإثبات ═══
LOAD-601 منهجية §20 المقيسة+تقرير الحقول الإلزامي            [P1·G6]
CHAOS-602 فئات الفشل كاملة+partial-migration-resume          [P1·G6]
REAUD-603 إعادة تدقيق مستقلة                                  [G7]

P3 (غير مجدول): timestamps-unify·multi-step-txn·orphan-cleanup·dir-auto
·graph-version-unify·events-table-decision·TTL-keys·chat-fix·brain-gate
```

## 27. سجل خطر الإصلاح

| التغيير | فشل بسبب الإصلاح | الاحتمال | الأثر | التخفيف | Rollback |
|---|---|---|---|---|---|
| مطالبة ذرّية | double-claim بlease قصيرة تحت Graph بطيء | منخفض | تكرار | 120s≫30s مهيأ + مرصود | flag off |
| idempotency فريد | كبت رد مشروع ثانٍ | منخفض جداً | ضياع رد | مفاتيح wamid-based؛ يدوي UUID | drop فهرس (additive) |
| lease recovery | resend بعد انهيار | نادر متوسط | تكرار نادر | sending→uncertain لا blind-requeue | MANUAL_ONLY أصلاً |
| **RECON MANUAL_ONLY** | ردود عالقة uncertain بانتظار مشغل | متوسط | تأخير رد | تنبيه فوري + عرض أدلة كاملة + قرار بدقيقة | — (هو الrollback) |
| firewall التعلم | فقد nuance سوقية | جزئي مؤكد | منخفض | تجميعات تحفظ الإشارة؛ KB يستعيد | للأمام فقط |
| مصنف الموافقة | تأخير موافقة حقيقية | متوسط | منخفض | approval.classified أسبوعياً + تنبيه ملخص للمالك | flag (غير موصى) |
| حاكم التكلفة | خنق مشترٍ نشط | منخفض | متوسط | حدود كريمة+whitelist+digest | رفع حدود |
| pragmas | hang webhook أطول تحت contention | منخفض | منخفض | bounded 15s مرصود | إزالة pragma |
| حراس retention | نمو DB | مؤكد | منخفض | مراجعة ربع سنوية | تخفيف شروط |
| auth pack | المالك مقفول من صندوقه | متوسط | متوسط | whitelist IP+reset موثق | CF-header mode |
| lang-v2 | قلب لغة قائمين | متوسط | متوسط | shadow أسبوع+وراثة conversation-language | flag off |
| MIG-201 | backfill يفسد/ينقطع جزئياً | منخفض | عالٍ | dry-run+عدادات+snapshot+**idempotent-restartable** | snapshot+flag |

## 28. ما يجب ألا يُفعل

- ❌ ادعاء exactly-once لدى المزود بأي صياغة.
- ❌ انتقال آلي uncertain→queued في الإصدار التأسيسي (MANUAL_ONLY).
- ❌ تحويل uncertain→sent بدليل heuristic صامت.
- ❌ إعادات عمياء بلا تصنيف خطأ؛ unknown_class بلا سقف attempts.
- ❌ drop schema/حذف بيانات أثناء الاستقرار؛ حذف صفوف outbox لإخفاء تاريخ.
- ❌ اعتبار chmod 600 تدويراً؛ إتلاف أدلة جنائية قبل التقييم.
- ❌ نص حر للعميل كتعليمات؛ delimiter كحد أمان وحيد.
- ❌ سماح للنموذج بالتفويض النهائي لأي فعل حساس أو لمس destructive paths.
- ❌ ترقية ai_inferred→verified بواسطة AI.
- ❌ Redis/Postgres/microservices بلا إشارات §20 المقيسة.
- ❌ تغيير شخصية البرومبت بلا سبب سلامة؛ خلط ميزات بالاستقرار؛ المس opt-out.
- ❌ تجاوز regression بمستواه المطلوب أو المواصلة بعد فشل GO gate.
- ❌ تغيير معمارية بصمت — STOP-and-report دائماً.

## 29. بوابات جاهزية الإنتاج

| البوابة | الإثبات الموضوعي |
|---|---|
| **G1 Message Safety** | مصفوفة §19.2 العشر + TEST-IN-01..05 كاملة خضراء؛ صفر تكرار تحت 20-kway concurrency؛ crash-after-acceptance ينتهي uncertain بمصالحة MANUAL مُختبَرة؛ صفر انتقالات غير قانونية؛ **سلامة استرجاع الوارد: لا replay بالزمن-حده، استرجاع بlease منتهية فقط، دليل الإتمام يُفحص دائماً** |
| **G2 Data Safety** | backup-fail←تنبيه<5د؛ restore-test أخضر؛ integrity ok؛ هجرة بعدادات مطابقة وقابلة للاستئناف؛ صفر حالات خارج النطاقات |
| **G3 Security** | مكشوفات-كاملة مُبطلة + رفض القديم مثبت؛ .env 600؛ brute-force يثبت؛ corpus حقن نظيف؛ تعقيم مثبت بسر مزيف؛ لا سر في أي سجل |
| **G4 AI Safety** | صفر تلوث cross-customer؛ موافقة 20/20؛ تعلم مهيكل بلا نص حر في system؛ أدوات مصنفة §10.3 والنموذج غير مفوِّض |
| **G5 Observability** | corr-id traceability كاملة؛ dedup صحيح e2e؛ uncertain/failure/backup مرئية؛ إعادة بناء incident من السجلات وحدها |
| **G6 Load/Failure** | تقرير حمل مقيس بحقول §20؛ كل فئات الفشل بسلوك مصمم؛ partial-migration resume؛ لا نمو خيوط هارب؛ **حماية التكلفة مثبتة: rate-limits + سقف عام + حماية ويبهوك-مكرر + human-mode صفر-LLM (TEST-COST-01..05)** |
| **G8 Implementation Discipline** | كل انحراف تنفيذي عن الخطة وثّق عبر بروتوكول §32 (STOP←EVIDENCE←REPORT←DECISION) — صفر ارتجال معماري صامت في سجل القرارات |
| **G7 Independent Re-Audit** | تدقيق جديد بمنهجية الأصل: 0 CRITICAL · 0 HIGH مفتوح قبل A/READY |

## 30. مراجعة ذاتية معادية

**Q: ماذا قد يرسل تكراراً بعد كل هذا؟**
نافذة crash-after-provider-acceptance فقط. تُعالج بـ sending-persist + uncertain + MANUAL reconciliation؛ التكرار يبقى ممكناً نظرياً فقط بقرار retry واعٍ بعلامة dup_risk. لا مسار آخر معروف.

**Q: قبول المزود + انهيار worker؟** sending→(lease)→uncertain→تنبيه→مشغل. موثق §9.
**Q: webhook توصيل متأخر؟** يحدّث delivery_status كدليل حتى على صف dead؛ لا إحياء send-state؛ يُسجل.
**Q: webhook مكرر؟** رتيب؛ اختباران 5,6.
**Q: خطأ مزود مجهول؟** unknown_class retryable-بحد→dead('unclassified'). مغطى.
**Q: DB كتب والرد ضاع؟** هذا حرفياً sending→uncertain؛ الدليل المحفوظ pre-send يجعل الصف قابلاً للقرار.
**Q: أسرار انكشفت فعلاً؟** سلسلة §6 بforensic-first؛ chmod ≠ revocation.
**Q: بيانات AI خاطئة؟** ai_inferred بconfidence ≤0.7 ولا ترقى أبداً؛ التعارض بauthority-first.
**Q: ما يمنع تنفيذ AI أفعالاً غير مصرح بها؟** §10.3: النموذج يقترح فقط؛ whitelist+owner+policy-gate+risk-classification قبل التنفيذ؛ destructive خارج متناوله كلياً.
**Q: تلوث cross-customer؟** التعلم مهيكل مجمّع في user-content؛ corpus يثبت؛ لا نص عميل في system.
**Q: هجرة نجحت نصفياً؟** scripts idempotent/re-runnable + guards؛ CHAOS يختبر الاستئناف.
**Q: backup نجح وrestore فشل؟** restore_test الشهري يكشف؛ فشله = STOP هجرات.
**Q: contention SQLite ارتفع؟** busy_timeout يخفف؛ إشارات §20 تطلق مراجعة التدرج (async-drain أولاً، Postgres أخيراً).
**Q: فشل GO gate؟** STOP السلسلة التابعة؛ لا مهمة تالية تبدأ (§24).
**Q: هل يستطيع وكيل تنفيذي تنفيذ هذا دون قرارات معمارية؟** يستطيع تنفيذ **المعمارية المعتمدة وتسلسل المهام دون إعادة تصميم النظام** — لكن هذا ليس تفويضاً مطلقاً: أي سلوك مستودع أو قيد schema أو سلوك مزود أو تفصيلة تنفيذ تخالف الخطة المعتمدة **يجب** أن تطلق: `STOP ← EVIDENCE ← REPORT ← DECISION` قبل أي انحراف معماري أو تغيير تبعي. البروتوكول الرسمي في §32.
**Q: هل ما زال بإمكان عامل بطيء نشط أن يُضاعف بمرور 10 دقائق؟** لا — استرجاع الوارد أصبح lease/state-based ثلاثياً (ACTIVE/STALE/COMPLETED/UNKNOWN §7.4)؛ الزمن وحده ليس شرطاً؛ TEST-IN-01..05 يثبت.
**Q: هل ما زال ممكناً نداءات LLM غير محدودة قبل COST-402؟** لا في الخطة الجديدة — COST-402 أصبح P1 يعقب AI-105 مباشرة وقبل توسيع حركة AI؛ TEST-COST-01..05 يثبت الحماية.
**Q: هل أحدثت هذه التعديلات حلقة تبعيات؟** لا — COST-402 يعتمد على AI-105 فقط (أمام كل العناقيد)؛ OUT-203 يبقى داخل بوابة العنقود؛ الترتيب خطي بلا دورات.

---

## 31. ترتيب التنفيذ النهائي

```
SEC-000 → OBS-101 → OBS-102 → BAK-103 → AI-104 ∥ AI-105
→ COST-402 (P1 — قبل أي توسيع AI أو حركة عملاء أوسع)
→ [MIG-201 → OUT-202 → OUT-203 → OUT-204 → OUT-205] (بوابة عنقود واحدة)
→ DB-301 → WA-302 → JOBS-304 → SRV-401 → UI-403
→ LOAD-601 + CHAOS-602 → [G1-G5 تُعلن] → AI-501(shadow) → FACT-502 → OFFR-503
→ REAUD-603 (G7) → PRODUCTION GATE
```
*(مرجعي؛ أي انحراف يوثق بمبرر. WA-303 وP3 خارج المسار الحرج.)*

## 32. تسليم وكيل التنفيذ

1. نفذ بالترتيب أعلاه؛ عنقود OUT-202..205 ببوابة GO مشتركة عبر مصفوفة العشر + TEST-IN-01..05.
2. كل مهمة بحقول القالب كاملة؛ مستوى regression حسب §19.1 (والعالي-الخطورة دائماً strong).
3. قيود: additive-only migrations؛ flags (`outbox_v2`,`approval_v2`,`lang_v2_shadow`,`cost_governor`,`outbox_uncertain_policy=manual_only`)؛ لا deps جديدة؛ opt-out غير قابل للمس.
4. **قاعدة سلطة التنفيذ (رسمية):** الوكيل ينفذ المعمارية المعتمدة وتسلسل المهام **دون إعادة تصميم النظام** — لكنه غير مفوَّض بالانحراف الصامت. أي سلوك مستودع أو قيد schema أو سلوك مزود أو تفصيلة تنفيذ تخالف الخطة يطلق البروتوكول أدناه.

### بروتوكول اكتشاف التنفيذ (IMPLEMENTATION DISCOVERY — إلزامي)

```
اكتشاف تنفيذي (سلوك/قيد/تفصيلة)
        ↓
هل يطابق الخطة المعتمدة؟
   ├── نعم ← تابع التنفيذ
   └── لا
        ↓
      STOP (توقف فوري — لا تعديلات تبعية)
        ↓
      التقط الدليل (file:line / مخرج أمر / حالة DB)
        ↓
      اشرح الأثر على الخطة (أي مهام/بوابات تتأثر)
        ↓
      اقترح انحرافاً أدنياً موثقاً
        ↓
      انتظر قرار الموافقة قبل المتابعة
```

**الوكيل ممنوع من الارتجال المعماري بصمت — في كل الحالات، دون استثناء.**

---

> **The implementation agent must not begin implementation until the revised remediation plan passes its own consistency review. After implementation begins, every task must pass its targeted tests, full regression, runtime verification, and GO gate before the next dependent task is started. Any unexpected architectural discovery, data anomaly, security issue, or customer-visible behavior outside the approved plan requires STOP-and-report before further modification.**

---

# FINAL REVIEW STATUS

- **Review date:** 2026-08-24
- **Files reviewed:** `REMEDIATION_PLAN_v1.1.md` (كاملاً، مرتين) · `PRODUCTION_AUDIT_2026-08-24.md` · `REMEDIATION_PLAN.md` (v1.0 للمرجعية)
- **Repository areas inspected (read-only):** channels/{outbox,coordinator,whatsapp,language,inbox,webhook_server}.py · storage/db.py + schema.sql · services/events.py + owner_alert.py · ops/{alerts,learning,jobs,scheduler,startup,recovery,backup,retention}.py · routing/providers.py · crm/service.py · cli.py · configs/{models,scheduler}.yaml · live DB forensics (outbox statuses/idempotency duplicates) · systemd units · `.env` permissions · `~/.bash_history` pattern count · docs cleanliness from real secrets (verified clean).
- **Corrections made in this pass:** R1 uncertain-policy→MANUAL_ONLY · R2 heuristic evidence downgraded to annotate-only + صراحة عدم وجود مصالحة authoritative · R3 سلسلة جنائية بسبع مراحل تبدأ بالحفظ · R4 ثلاثة نطاقات حالة منفصلة + failed_retryable/sending صريحة + unknown_class · R5 قسم تفويض أدوات AI بتصنيف المستودع الفعلي · R6 تعارض facts بauthority/freshness/semantics/provenance + حظر ترقية AI · R7 regression متدرج بأربعة مستويات · R8 مصفوفة outbox عشر اختبارات كاملة الأركان · إضافة: webhook-متأخر-على-dead، partial-migration-resume، restore-fail-stop، حقول TARGET في القالب، مراجعة ذاتية معادية §30.
- **Final recommendation pass completed (الجولة الثالثة):**
  - **inbound idempotency recovery corrected (R9):** حُذفت قاعدة «pending >10د» من كل المواضع؛ استُبدلت بمنطق ACTIVE/STALE/COMPLETED/UNKNOWN lease-based ثلاثي الشروط؛ أُضيفت TEST-IN-01..05 وبوابات GO/STOP خاصة؛ حدّثت §7.4 + §19.2 + OUT-203 + G1.
  - **COST-402 moved to safety phase (R10):** من P2/Phase-5 إلى **P1 مباشرة بعد AI-105** بأدلة مستودعية موثقة في §5؛ أُضيفت TEST-COST-01..05 (§19.3)؛ حُدّثت: الأولويات، WS-COST dependency، رسم التبعيات §25، Backlog §26، ترتيب التنفيذ §31، بوابة G6.
  - **implementation-agent authority corrected (R11):** حُذف الادعاء المطلق «دون قرارات معمارية»؛ استُبدل بصياغة «دون إعادة تصميم + بروتوكول IMPLEMENTATION DISCOVERY الرسمي (STOP←EVIDENCE←REPORT←DECISION)» في §30 و§32 + بوابة G8 جديدة.
- **Cross-consistency check (منجز):** لا موضع يذكر «10د ← إعادة» إلا مشروطاً بالثلاثي · COST-402 في موضعها الجديد بكل المراجع (§1/§4/§5/§19/§25/§26/§29/§31) · لا ادعاء سلطة مطلق متبقٍ · لا حلقات تبعيات جديدة.
- **Remaining risks (documented, non-blocking):** نافذة at-least-once النظرية بعد crash-after-acceptance (معالجة بالمصالحة اليدوية) · أرقام الأداء preliminary حتى LOAD-601 · قرارات SEC-000 تتطلب تنفيذ مالك (عملية لا معمارية).
- **Blocking issues:** لا يوجد.

**PLAN STATUS: READY FOR IMPLEMENTATION**

---
*المدخلات: [PRODUCTION_AUDIT_2026-08-24.md](./PRODUCTION_AUDIT_2026-08-24.md) · [REMEDIATION_PLAN.md](./REMEDIATION_PLAN.md) (v1.0 — لم يُعدَّل)*
