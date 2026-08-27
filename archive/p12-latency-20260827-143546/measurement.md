# P1-2 — القياس الحي الختامي

## L8 الدفعة الرئيسية (10 رسائل موقعة)
| # | نوع | extract.gate | mode | receipt→draft1 | نداءات draft | blocked | wall→enq | wall HTTP |
|---|---|---|---|---|---|---|---|---|
| 1 ar أولى | مطعم+قائمة | skip(حتمي) | NEED | 43.0s | 1 | لا | 43.0s | 45.70 |
| 2 ar متابعة سعر | سعر | legacy-price مسار | — | 17.0 | 1 | لا | 17.0s | 18.79 |
| 3 en أولى | gym site | call (بلا alias) | NEED | 66.0 | 1 | لا | 66.0s | 67.61 |
| 4 en متابعة توسعة | member area | call (رقم+غموض) | NEED | 37.0 | 1 | لا | 37.0s | 39.43 |
| 5 ar أولى | عيادة | call | NEED | 44.0 | 1 | لا | 44.0s | 45.69 |
| 6 ar متابعة سعر | أسعار؟ | skip(حتمي) | NEED | 28.0 | 1 | لا | 28.0s | 30.05 |
| 7 ar أولى | عقارات فلترة | skip(حتمي) | NEED | 20.0 | 1 | لا | 20.0s | 22.63 |
| 8 ar متابعة توسعة+نفي | حجز→سحب | call (negation) | SHAPING | 61.0 | 1 | لا | 61.0s | 63.71 |
| 9 ar أولى قانوني | عقد اعتراض | call | OPENING | 23.0 | 1 | handoff | handoff | 30.44 |
| 10 en متابعة legal-lead | status? | — | — | 0 (دون LLM) | 0 | — | يوجّه بشري | 0.14 |

- router retries: صفر في كل الرسائل (مسودة واحدة لكل cid، لا سطور إعادة).
- نداءات LLM للرسائل: extraction skipped على 3 من 5 المسارات النمطية الأولى/المتابعات (الرسائل 1، 6، 7) → توفير 3 نداءات استخراج كاملة؛ يتطابق مع قاعدة الأمان (أي غموض/أرقام/نفي = نداء).
- الأزمنة المتوسطة: أول رسالة ≈39s، متابعة ≈35s — فوق الهدف الإرشادي (≤30/≤10). أين ذهب الزمن: جزء الرسم يحتل كل الجدار تقريباً (GLM gen ~20-60s variance) وgate أنهى مرحلة الاستخراج إلى <0.2s عندما تحقق (msg1: receipt→route.mode=0.14s مقابل 17-34s تاريخياً).

## موجة LW/LX بعد إصلاح language-lock
## first-pass rate (n=140 مسودة حية فريدة تحت build جديد)
| نافذة | n | first-pass | السبب المهيمن |
|---|---|---|---|
| قبل lock | 118 | 84.7% | language_mismatch:ar ×15 |
| **بعد lock (تعديل واحد مستهدف)** | 22 | **90.9% ✓** | too_many_questions ×2 |
- البند 5: التعديل الواحد استُخدم على السبب الفعلي (قفل اللغة) وليس أسئلة-الحد-الأقصى؛ محفوظ في برومبت نظام _draft_reply: "LANGUAGE LOCK ...".

## prompt diet قبل/بعد (e2e، أحرف، fixture حقيقي)
- NEED_ar: 3100→2831 (−269، −9%)
- SHAPING/OBJECTION/ESCALATION: retriever لا يستدعى أصلاً بهذه الأنماط (اكتشاف) — slicing يحمي أي حقن مستقبلي. القرارات متطابقة: full regression 750 OK.

## BUG خارج القائمة البيضاء (موثق فقط)
amancore/channels/outbox.py:291 — `_dt.timedelta(...)` بينما الاستيراد `datetime as _dt` فقط ⇒ AttributeError عند valve.hold → webhook 500 + صفوف processing عالقة (من دفعة compliance-kit da299b7). معالجة تشغيلية مؤقتة: requeue 7 صفوف عبر SQL (لإصلاح الكود: `_td.timedelta`).
