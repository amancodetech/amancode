"""Language detection (AR / ID / EN) — deterministic, no guessing."""

from __future__ import annotations

import re

_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF]")
_INDONESIAN_KEYWORDS = [
    "terima kasih", "saya", "kami", "mau", "butuh", "bisa", "tolong", "harga",
    "berapa", "pesan", "pesanan", "bagaimana", "boleh", "ingin", "meningkat",
    "pak", "bu", "yang", "sudah", "belum", "membutuhkan",
]


class LanguageDetector:
    def detect(self, text: str) -> str:
        t = text or ""
        if _ARABIC_SCRIPT.search(t):
            return "ar"
        lower = t.lower()
        if any(kw in lower for kw in _INDONESIAN_KEYWORDS):
            return "id"
        return "en"
