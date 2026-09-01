/* ═══════════════════════════════════════════
   AMANCODE — interactions + trilingual i18n
   ═══════════════════════════════════════════ */
"use strict";

/* mark JS availability — reveal animations only run when JS is active */
document.documentElement.classList.add("js");

/* ── WhatsApp number (owner updates this one place) ── */
const WHATSAPP_NUMBER = "6281234567890"; // TODO(owner): ganti dengan nomor WhatsApp bisnis
const WA_TEXT = {
  id: "Halo AmanCode, saya ingin konsultasi tentang kebutuhan digital bisnis saya.",
  en: "Hello AmanCode, I would like to consult about my business's digital needs.",
  ar: "مرحبًا AmanCode، أرغب في استشارة حول الاحتياجات الرقمية لعملي التجاري."
};

/* ── translations ── */
const I18N = {
  id: {
    skip: "Lewati ke konten",
    nav_services: "Layanan", nav_packages: "Paket", nav_process: "Cara Kerja",
    nav_why: "Kenapa Kami", nav_contact: "Kontak", cta_whatsapp: "WhatsApp",

    hero_eyebrow: "Perusahaan Solusi Digital — Indonesia",
    hero_title: "Sistem digital untuk bisnis yang terus bertumbuh.",
    hero_sub: "Kami merancang, membangun, dan memelihara website, aplikasi, serta sistem yang menjalankan bisnis Anda — dengan lingkup jelas, proposal transparan, dan perawatan jangka panjang.",
    hero_cta_primary: "Mulai Konsultasi Gratis",
    hero_cta_secondary: "Lihat Layanan",
    hero_p1: "Website bisnis multibahasa & aplikasi web kustom",
    hero_p2: "Solusi terintegrasi: website, WhatsApp & otomasi AI",
    hero_p3: "Skema pembayaran jelas: 50% di muka, 50% serah terima",
    hero_card1: "Website & Web App",
    hero_card2: "Mini-ERP & Mobile",
    hero_mock_arch: "Sistem Bisnis Digital",
    hero_mock_status: "Sistem Aktif",
    hero_mock_perf: "Indeks Performa",
    hero_mock_mod1: "Platform Web",
    hero_mock_mod2: "Cloud ERP",
    hero_mock_mod3: "Otomasi AI",

    svc_eyebrow: "Layanan Kami",
    svc_title: "Empat pilar solusi digital AmanCode",
    svc_sub: "Dari kehadiran digital pertama hingga sistem operasional terintegrasi — dibangun sesuai skala bisnis Anda.",
    tier_core: "Inti", tier_premium: "Premium", tier_entry: "Tahap Awal", tier_care: "Berkelanjutan",
    svc1_title: "Business Website System",
    svc1_desc: "Website perusahaan multibahasa yang dibangun sebagai sistem: struktur konten rapi, integrasi WhatsApp, dan siap dikembangkan.",
    svc2_title: "Custom Web Application",
    svc2_desc: "Aplikasi web yang dirancang khusus mengikuti alur kerja Anda: pemesanan, katalog, hingga tools internal tim.",
    svc3_title: "Business System / Mini-ERP",
    svc3_desc: "Sistem terintegrasi yang menyatukan penjualan, inventori, penagihan, dan laporan dalam satu tempat.",
    svc4_title: "Mobile App",
    svc4_desc: "Aplikasi mobile premium yang terhubung langsung dengan sistem bisnis Anda, untuk pelanggan maupun tim internal.",

    pkg_eyebrow: "Jenjang Layanan",
    pkg_title: "Mulai dari ukuran yang tepat, tumbuh bertahap",
    pkg_sub: "Setiap bisnis berbeda. Kami menyusun lingkup yang pas — harga final selalu disepakati bersama dalam proposal tertulis.",
    pkg1_title: "Business Presence Starter",
    pkg1_desc: "Pintu masuk: kehadiran digital profesional agar bisnis Anda mudah ditemukan dan dihubungi.",
    pkg2_title: "Business Website System",
    pkg2_desc: "Website sistem lengkap multibahasa — fondasi digital inti perusahaan Anda.",
    pkg3_title: "Custom Web Application",
    pkg3_desc: "Web app kustom untuk proses bisnis unik Anda — dari reservasi hingga portal pelanggan.",
    pkg4_title: "Mini-ERP & Mobile App",
    pkg4_desc: "Level premium: sistem operasional terintegrasi dan aplikasi mobile untuk menskalakan operasi.",
    pkg5_title: "Care Plan",
    pkg5_desc: "Perawatan berkelanjutan tiga tingkat: pemeliharaan, pembaruan, dan penyempurnaan berkelanjutan setelah serah terima.",
    pkg_cta: "Minta Proposal Lingkup & Harga",

    proc_eyebrow: "Cara Kerja",
    proc_title: "Proses yang jelas dari awal hingga serah terima",
    proc_sub: "Tanpa kejutan. Setiap tahap disepakati tertulis sebelum dikerjakan.",
    proc1_t: "Konsultasi", proc1_d: "Diskusi gratis via WhatsApp untuk memahami kebutuhan dan tujuan bisnis Anda.",
    proc2_t: "Proposal & Lingkup", proc2_d: "Proposal tertulis dengan lingkup jelas dan tetap. Jika harga melebihi anggaran, kami sempitkan lingkup — bukan kualitas.",
    proc3_t: "Pembangunan", proc3_d: "Pengerjaan dengan skema pembayaran 50% di muka dan 50% saat serah terima.",
    proc4_t: "Serah Terima", proc4_d: "Peluncuran, pelatihan singkat penggunaan, dan dokumentasi serah terima.",
    proc5_t: "Care Plan", proc5_d: "Perawatan dan penyempurnaan berkelanjutan melalui paket Care Plan bertingkat.",

    why_eyebrow: "Kenapa AmanCode",
    why_title: "Fokus pada satu hal: sistem yang benar-benar bekerja untuk bisnis Anda",
    why1: "Website bisnis multibahasa dan aplikasi web kustom, dibangun dengan standar profesional.",
    why2: "Solusi terintegrasi: website, WhatsApp, dan otomasi AI dalam satu kesatuan.",
    why3: "Gaya kerja jelas dan berorientasi hasil — lingkup tertulis, progres terukur.",
    why4: "Dukungan berbahasa: Indonesia, Inggris, dan Arab.",
    why5: "Relasi jangka panjang melalui Care Plan, bukan proyek sekali lewat.",

    cta_eyebrow: "Mulai Sekarang",
    cta_title: "Ceritakan kebutuhan bisnis Anda hari ini",
    cta_sub: "Konsultasi awal gratis via WhatsApp. Balasan cepat pada jam kerja (WITA).",
    cta_whatsapp_btn: "Chat via WhatsApp",
    cta_email: "Kirim Email",
    cta_note: "AmanCode — melayani bisnis di Indonesia & pasar lintas negara"
  },

  en: {
    skip: "Skip to content",
    nav_services: "Services", nav_packages: "Packages", nav_process: "How We Work",
    nav_why: "Why Us", nav_contact: "Contact", cta_whatsapp: "WhatsApp",

    hero_eyebrow: "Digital Solutions Company — Indonesia",
    hero_title: "Digital business systems for growing companies.",
    hero_sub: "We design, build and maintain the websites, applications and systems that run your business — with clear scope, transparent proposals and long-term care.",
    hero_cta_primary: "Start a Free Consultation",
    hero_cta_secondary: "View Services",
    hero_p1: "Multilingual business websites & custom web applications",
    hero_p2: "Integrated solutions: website, WhatsApp & AI automation",
    hero_p3: "Clear payment terms: 50% upfront, 50% on delivery",
    hero_card1: "Website & Web App",
    hero_card2: "Mini-ERP & Mobile",
    hero_mock_arch: "Digital Systems",
    hero_mock_status: "System Active",
    hero_mock_perf: "Performance Index",
    hero_mock_mod1: "Web Platforms",
    hero_mock_mod2: "Cloud ERP",
    hero_mock_mod3: "AI Automations",

    svc_eyebrow: "Our Services",
    svc_title: "The four pillars of AmanCode digital solutions",
    svc_sub: "From your first digital presence to fully integrated operating systems — built to match the scale of your business.",
    tier_core: "Core", tier_premium: "Premium", tier_entry: "Entry", tier_care: "Recurring",
    svc1_title: "Business Website System",
    svc1_desc: "A multilingual company website built as a system: clean content structure, WhatsApp integration, ready to grow.",
    svc2_title: "Custom Web Application",
    svc2_desc: "Web applications designed around your exact workflow: bookings, catalogs and internal team tools.",
    svc3_title: "Business System / Mini-ERP",
    svc3_desc: "An integrated system connecting sales, inventory, invoicing and reporting in one place.",
    svc4_title: "Mobile App",
    svc4_desc: "Premium mobile apps connected directly to your business systems — for customers and internal teams.",

    pkg_eyebrow: "Service Ladder",
    pkg_title: "Start at the right size, grow step by step",
    pkg_sub: "Every business is different. We shape a scope that fits — final pricing is always agreed together in a written proposal.",
    pkg1_title: "Business Presence Starter",
    pkg1_desc: "The entry point: a professional digital presence so your business is easy to find and reach.",
    pkg2_title: "Business Website System",
    pkg2_desc: "A complete multilingual website system — the digital foundation of your company.",
    pkg3_title: "Custom Web Application",
    pkg3_desc: "Custom web apps for your unique processes — from reservations to customer portals.",
    pkg4_title: "Mini-ERP & Mobile App",
    pkg4_desc: "Premium tier: integrated operating systems and mobile apps that scale your operations.",
    pkg5_title: "Care Plan",
    pkg5_desc: "Three-tier ongoing care: maintenance, updates and continuous improvement after handover.",
    pkg_cta: "Request a Scope & Price Proposal",

    proc_eyebrow: "How We Work",
    proc_title: "A clear process from first call to handover",
    proc_sub: "No surprises. Every stage is agreed in writing before work begins.",
    proc1_t: "Consultation", proc1_d: "A free WhatsApp consultation to understand your business needs and goals.",
    proc2_t: "Proposal & Scope", proc2_d: "A written proposal with clear, fixed scope. If budget is tight we narrow the scope — never the quality.",
    proc3_t: "Build", proc3_d: "Development under clear payment terms: 50% upfront and 50% on delivery.",
    proc4_t: "Handover", proc4_d: "Launch, a short training session, and complete handover documentation.",
    proc5_t: "Care Plan", proc5_d: "Ongoing maintenance and improvement through tiered Care Plans.",

    why_eyebrow: "Why AmanCode",
    why_title: "Focused on one thing: systems that truly work for your business",
    why1: "Multilingual business websites and custom web applications, built to professional standards.",
    why2: "Integrated solutions: website, WhatsApp and AI automation as one whole.",
    why3: "A clear, outcome-focused way of working — written scope, measurable progress.",
    why4: "Support in three languages: Indonesian, English and Arabic.",
    why5: "Long-term relationships through Care Plans — not one-off projects.",

    cta_eyebrow: "Get Started",
    cta_title: "Tell us what your business needs today",
    cta_sub: "Free initial consultation via WhatsApp. Fast replies during working hours (WITA).",
    cta_whatsapp_btn: "Chat on WhatsApp",
    cta_email: "Send an Email",
    cta_note: "AmanCode — serving businesses in Indonesia & cross-border markets"
  },

  ar: {
    skip: "الانتقال إلى المحتوى",
    nav_services: "خدماتنا", nav_packages: "الباقات", nav_process: "طريقة العمل",
    nav_why: "لماذا نحن", nav_contact: "تواصل", cta_whatsapp: "واتساب",

    hero_eyebrow: "شركة حلول رقمية — إندونيسيا",
    hero_title: "أنظمة رقمية لأعمال تجارية تنمو باستمرار.",
    hero_sub: "نصمم ونبني ونصون المواقع والتطبيقات والأنظمة التي تدير عملك — بنطاق واضح وعروض شفافة ورعاية طويلة الأمد.",
    hero_cta_primary: "ابدأ استشارة مجانية",
    hero_cta_secondary: "تصفح الخدمات",
    hero_p1: "مواقع أعمال متعددة اللغات وتطبيقات ويب مخصصة",
    hero_p2: "حلول متكاملة: الموقع، واتساب، وأتمتة الذكاء الاصطناعي",
    hero_p3: "شروط دفع واضحة: 50% مقدمًا و50% عند التسليم",
    hero_card1: "المواقع وتطبيقات الويب",
    hero_card2: "Mini-ERP وتطبيقات الجوال",
    hero_mock_arch: "الأنظمة الرقمية",
    hero_mock_status: "النظام متصل",
    hero_mock_perf: "مؤشر الأداء",
    hero_mock_mod1: "منصات الويب",
    hero_mock_mod2: "Cloud ERP",
    hero_mock_mod3: "أتمتة الذكاء الاصطناعي",

    svc_eyebrow: "خدماتنا",
    svc_title: "أربع ركائز لحلول AmanCode الرقمية",
    svc_sub: "من أول حضور رقمي إلى أنظمة تشغيل متكاملة — مبنية على مقاس عملك.",
    tier_core: "أساسي", tier_premium: "متقدم", tier_entry: "بداية", tier_care: "مستمر",
    svc1_title: "نظام موقع الأعمال",
    svc1_desc: "موقع شركة متعدد اللغات مبني كنظام متكامل: بنية محتوى مرتبة وتكامل مع واتساب وقابلية تطوير.",
    svc2_title: "تطبيق ويب مخصص",
    svc2_desc: "تطبيقات ويب مصممة خصيصًا وفق سير عملك: الحجوزات والكتالوجات وأدوات الفريق الداخلية.",
    svc3_title: "نظام أعمال / Mini-ERP",
    svc3_desc: "نظام متكامل يجمع المبيعات والمخزون والفوترة والتقارير في مكان واحد.",
    svc4_title: "تطبيق جوال",
    svc4_desc: "تطبيقات جوال متقدمة مرتبطة مباشرة بأنظمة عملك — لعملائك وفريقك على حد سواء.",

    pkg_eyebrow: "سلّم الخدمات",
    pkg_title: "ابدأ بالمقاس المناسب وانمو درجة درجة",
    pkg_sub: "كل نشاط تجاري مختلف. نصيغ النطاق المناسب لك — ويبقى السعر النهائي متفقًا عليه دائمًا في عرض مكتوب.",
    pkg1_title: "باقة الحضور التجاري",
    pkg1_desc: "نقطة البداية: حضور رقمي احترافي ليكون عملك سهل الوصول والاكتشاف.",
    pkg2_title: "نظام موقع الأعمال",
    pkg2_desc: "نظام موقع متعدد اللغات — الأساس الرقمي لشركتك.",
    pkg3_title: "تطبيق ويب مخصص",
    pkg3_desc: "تطبيقات مخصصة لعملياتك الفريدة — من الحجوزات إلى بوابات العملاء.",
    pkg4_title: "Mini-ERP وتطبيق الجوال",
    pkg4_desc: "المستوى المتقدم: أنظمة تشغيل متكاملة وتطبيقات جوال لتوسيع عملياتك.",
    pkg5_title: "خطة الرعاية",
    pkg5_desc: "رعاية مستمرة بثلاث فئات: صيانة وتحديثات وتحسينات بعد التسليم.",
    pkg_cta: "اطلب عرض نطاق وسعر",

    proc_eyebrow: "طريقة العمل",
    proc_title: "مسار واضح من أول اتصال حتى التسليم",
    proc_sub: "بدون مفاجآت. كل مرحلة متفق عليها كتابيًا قبل بدء التنفيذ.",
    proc1_t: "الاستشارة", proc1_d: "استشارة مجانية عبر واتساب لفهم احتياجات عملك وأهدافه.",
    proc2_t: "العرض والنطاق", proc2_d: "عرض مكتوب بنطاق واضح وثابت. إن ضاقت الميزانية نضيّق النطاق — لا الجودة.",
    proc3_t: "التنفيذ", proc3_d: "العمل بشروط دفع واضحة: 50% مقدمًا و50% عند التسليم.",
    proc4_t: "التسليم", proc4_d: "الإطلاق مع تدريب قصير على الاستخدام وتوثيق كامل للتسليم.",
    proc5_t: "خطة الرعاية", proc5_d: "صيانة وتحسينات مستمرة عبر خطط رعاية متدرجة.",

    why_eyebrow: "لماذا AmanCode",
    why_title: "تركيز واحد: أنظمة تعمل حقًا من أجل عملك",
    why1: "مواقع أعمال متعددة اللغات وتطبيقات ويب مخصصة بمعايير مهنية.",
    why2: "حلول متكاملة: الموقع وواتساب وأتمتة الذكاء الاصطناعي كوحدة واحدة.",
    why3: "أسلوب عمل واضح موجه نحو النتائج — نطاق مكتوب وتقدم قابل للقياس.",
    why4: "دعم بثلاث لغات: الإندونيسية والإنجليزية والعربية.",
    why5: "علاقات طويلة الأمد عبر خطط الرعاية — لا مشاريع عابرة.",

    cta_eyebrow: "ابدأ الآن",
    cta_title: "أخبرنا بما يحتاجه عملك اليوم",
    cta_sub: "استشارة أولى مجانية عبر واتساب. رد سريع خلال ساعات العمل (WITA).",
    cta_whatsapp_btn: "الدردشة على واتساب",
    cta_email: "أرسل بريدًا",
    cta_note: "AmanCode — نخدم الأعمال في إندونيسيا والأسواق العابرة للحدود"
  }
};

/* ── language switching ── */
const htmlEl = document.documentElement;
function applyLang(lang) {
  const dict = I18N[lang];
  if (!dict) return;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) el.innerHTML = dict[key];
  });
  htmlEl.setAttribute("lang", lang);
  htmlEl.setAttribute("dir", lang === "ar" ? "rtl" : "ltr");
  document.title = lang === "ar" ? "AmanCode — أنظمة الأعمال الرقمية"
                 : lang === "en" ? "AmanCode — Digital Business Systems"
                 : "AmanCode — Sistem Bisnis Digital";
  document.querySelectorAll(".lang-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.lang === lang));
  updateWaLinks(lang);
  localStorage.setItem("amancode_lang", lang);
}

function updateWaLinks(lang) {
  document.querySelectorAll("[data-wa]").forEach(a => {
    a.href = `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(WA_TEXT[lang] || WA_TEXT.id)}`;
  });
}

// lang buttons
document.querySelectorAll(".lang-btn").forEach(b => {
  b.addEventListener("click", () => applyLang(b.dataset.lang));
});

/* ── mobile nav ── */
const navToggle = document.getElementById("navToggle");
const mainNav = document.getElementById("mainNav");
navToggle.addEventListener("click", () => {
  const open = mainNav.classList.toggle("open");
  navToggle.setAttribute("aria-expanded", String(open));
});
mainNav.querySelectorAll("a").forEach(a =>
  a.addEventListener("click", () => {
    mainNav.classList.remove("open");
    navToggle.setAttribute("aria-expanded", "false");
  }));

/* ── reveal on scroll ── */
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add("visible"); observer.unobserve(e.target); }
    });
  }, { threshold: 0.14 });
  document.querySelectorAll(".reveal").forEach(el => observer.observe(el));
} else {
  document.querySelectorAll(".reveal").forEach(el => el.classList.add("visible"));
}

/* ── init ── */
applyLang(localStorage.getItem("amancode_lang") || localStorage.getItem("amancore_lang") || "id");
