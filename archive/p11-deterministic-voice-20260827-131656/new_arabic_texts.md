# P1-1 — النصوص العربية الحرفية الجديدة + بنود التحقق

## 2.1 الإفصاح عن الهوية (حتمي)
AR:
"أنا مساعد رقمي في AmanCore وأعمل مع فريق حقيقي يساندك؛ ما الخدمة التي أُساعدك بها الآن؟"
EN:
"I'm a digital assistant at AmanCore working alongside our real team — what can we help you with right now?"

## 2.2 التصعيد الحتمي
legal AR:
"هذا موضوع قانوني/تعاقدي نحيله إلى فريقنا المختص للمراجعة بدقة، ولن أُصدر أي قرار أو التزام من جهتي هنا."
legal EN:
"This is a legal/contractual matter — I'll route it to our specialist team for careful review; no decision or commitment from me here."
financial AR: "هذا موضوع مالي نحيله إلى فريقنا المختص لدراسته وفق سياساتنا المعتمدة، ولن أقدم أي التزام من جهتي هنا."
urgent AR: "طلبك عاجل وسأرفعه فورًا لفريقنا ليتولاه مباشرة."

## 2.3 قالب T1 العربي (بنية مطابقة للإنجليزي)
افتتاحيات الـ rotation الحتمي (hash-seed على external_message_id):
1. "سؤال في محله!"
2. "بكل سرور أوضح لك هذا أولًا:"
3. "تفضل الصورة العامة عن النطاق:"
4. "خلني أعطيك فكرة صادقة من البداية:"
5. "هذه نقطة البداية المعلنة لدينا:"
6. "أهلًا بك؛ لنبدأ من الأساسيات:"
الهيكل:
"{opener} المشاريع في فئة «{category}» تبدأ عادةً من {low} وقد تصل إلى حوالي {high} {currency}{hint_ar} بحسب تفاصيل النطاق. الرقم النهائي نثبّته معك بعد تأكيد المتطلبات؛ ما أهم جزء تودّ أن نبدأ به؟"
مثال فعلي حي (متجر/website، LLM ميت — من الاختبار):
"... نقطة البداية... من {band_low} إلى حوالي {band_high} دولار أمريكي بحسب تفاصيل النطاق..." (الأرقام verbatim من Brain price_bands_public)

## 2.4 deferral العام المحسّن
AR: "وصلني طلبك وأتابعه معك. ما الخدمة التي تهمك؟"
EN: "Got your message — I'm on it with you. What service do you need?"
(بلا وعود زمنية، بلا أسعار، بلا claims)

## الحزمة
knowledge/packs/service_details.v1.yaml — 6 خدمات بـ statement_kind=RECOMMENDATION وprovenance لكل سجل، validate_all = valid ✓

## الكمون (عدم الانحدار)
لا استدعاءات LLM جديدة في أي مسار من الدفعة.
AFTER (3+3 عبر webhook):
first avg=68.29s [92.95, 51.51, 60.41] | follow avg=14.50s [13.73, 16.89, 12.88]
BEFORE مرجعية (نفس الإعداد pre-batch، W-run): first≈55.9s، follow≈19.2s
الفروق ضمن تشتت سيرفر Zhipu (صفر quality.blocked خلال القياس؛ كل cid بمسودة واحدة).
الشذوذ 92.95s أُثبت أنه نداء واحد بلا regen من السجل.
