"""AmanCode Master Brand Tokens & Design System Specification.

Brand Philosophy:
- Precision over decoration
- Clarity over complexity
- Recognition over novelty
- Restraint over spectacle
- Optical balance over mathematical perfection
- Craftsmanship over effects

Anti-AI Direction:
- No neon / glow / cyberpunk
- No excessive blue/purple gradients
- No generic shields, locks, or circuit boards
- Clean, architectural, engineered geometry
"""

from __future__ import annotations
from pathlib import Path

# Paths to authoritative visual brand assets
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
LOGO_PATH = ASSETS_DIR / "LOGO.png"
APP_ICON_PATH = ASSETS_DIR / "app_icon_1024.png"
AVATAR_WHITE_PNG = ASSETS_DIR / "amancode_avatar_white_1024.png"
AVATAR_WHITE_JPG = ASSETS_DIR / "amancode_avatar_white_1024.jpg"
GEOMETRY_PATH = ASSETS_DIR / "الهندسة.png"
BRAND_SYSTEM_PATH = ASSETS_DIR / "الهوية البصرية.png"

# Brand Naming
BRAND_NAME_EN = "AmanCode"
BRAND_NAME_AR = "أمان كود"
TAGLINE_EN = "Advanced technology engineered with security and intelligence."
TAGLINE_AR = "تقنية متقدمة مصممة بأعلى معايير الأمان والذكاء."

# Master Color Palette (Restrained, Editorial & Mature)
COLOR_PRIMARY = "#17191C"        # Graphite Black — authority, engineering, security
COLOR_SECONDARY = "#F3F1EA"      # Warm Ivory — canvas, editorial clarity, warmth
COLOR_ACCENT = "#236B57"         # Deep Emerald — proprietary accent, used with restraint

# Surface & UI Tokens (Dark Mode)
COLOR_DARK_BG = "#17191C"
COLOR_DARK_SURFACE = "#1F2328"
COLOR_DARK_BORDER = "#2E343D"
COLOR_DARK_TEXT_PRIMARY = "#F3F1EA"
COLOR_DARK_TEXT_MUTED = "#9CA3AF"

# Surface & UI Tokens (Light Mode)
COLOR_LIGHT_BG = "#F3F1EA"
COLOR_LIGHT_SURFACE = "#FFFFFF"
COLOR_LIGHT_BORDER = "#E2DFD7"
COLOR_LIGHT_TEXT_PRIMARY = "#17191C"
COLOR_LIGHT_TEXT_MUTED = "#575E6A"

# Typography Families
FONT_FAMILY_EN = "Plus Jakarta Sans"
FONT_FAMILY_AR = "Noto Kufi Arabic"
FONT_FAMILY_MONO = "JetBrains Mono"
