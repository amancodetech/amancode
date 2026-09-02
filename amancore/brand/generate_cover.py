"""Renders an ultra-high-resolution, architectural Facebook Cover Banner for AmanCode.

Adheres to:
- Official Brand Palette: Graphite Black (#17191C), Warm Ivory (#F3F1EA), Deep Emerald (#236B57)
- Dimensions: 1640 x 924 px
- Pure Typography & High-Contrast Layout without missing emoji glyphs
"""

from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

def shape_ar(text: str) -> str:
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text

def create_facebook_cover(output_path: str) -> str:
    width, height = 1640, 924
    img = Image.new("RGB", (width, height), color="#17191C")
    draw = ImageDraw.Draw(img)

    # 1. Architectural Structural Card
    margin_x, margin_y = 50, 40
    card_box = [margin_x, margin_y, width - margin_x, height - margin_y]
    draw.rounded_rectangle(card_box, radius=24, fill="#1E2228", outline="#2E343D", width=3)

    # Top Accent Line (Deep Emerald #236B57)
    draw.line([(margin_x + 30, margin_y), (width - margin_x - 30, margin_y)], fill="#236B57", width=6)

    # 2. Load and Embed Crisp Logo
    logo_path = "/home/omar/Desktop/work/aman-core/assets/LOGO.png"
    if os.path.exists(logo_path):
        logo_img = Image.open(logo_path).convert("RGBA")
        bbox = logo_img.getbbox()
        if bbox:
            logo_img = logo_img.crop(bbox)
        target_logo_h = 100
        target_logo_w = int(logo_img.width * (target_logo_h / logo_img.height))
        sharp_logo = logo_img.resize((target_logo_w, target_logo_h), Image.Resampling.LANCZOS)
        img.paste(sharp_logo, (margin_x + 60, margin_y + 45), sharp_logo)

    # 3. Typography Loading
    font_kufi_bold = "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf"
    font_kufi_reg = "/usr/share/fonts/truetype/noto/NotoKufiArabic-Regular.ttf"
    font_sans_bold = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"

    font_brand = ImageFont.truetype(font_kufi_bold, 40)
    font_sub_brand = ImageFont.truetype(font_kufi_reg, 24)
    font_headline = ImageFont.truetype(font_kufi_bold, 44)
    font_subtitle = ImageFont.truetype(font_kufi_reg, 28)
    font_badge = ImageFont.truetype(font_kufi_bold, 24)
    font_footer = ImageFont.truetype(font_kufi_reg, 24)
    font_footer_bold = ImageFont.truetype(font_kufi_bold, 26)

    # Header Text
    draw.text((margin_x + 180, margin_y + 55), "AmanCode", fill="#F3F1EA", font=font_brand)
    draw.text((margin_x + 180, margin_y + 110), shape_ar("أمان كود • شريكك التقني والهندسي المتكامل"), fill="#9CA3AF", font=font_sub_brand)

    draw.text((width - margin_x - 260, margin_y + 65), "ENGINEERED • AI", fill="#236B57", font=font_sub_brand)
    draw.line([(margin_x + 60, margin_y + 170), (width - margin_x - 60, margin_y + 170)], fill="#2E343D", width=2)

    # Main Center Headline & Subtitle
    headline_text = shape_ar("حلول برمجية وذكاء اصطناعي وهويات بصرية متكاملة")
    hw = draw.textlength(headline_text, font=font_headline)
    draw.text(((width - hw) // 2, 230), headline_text, fill="#F3F1EA", font=font_headline)

    subtitle_text = shape_ar("تطوير المنصات والمتاجر • أتمتة الأعمال • بناء الهوية التجارية والأنظمة")
    sw = draw.textlength(subtitle_text, font=font_subtitle)
    draw.text(((width - sw) // 2, 310), subtitle_text, fill="#A0A7B5", font=font_subtitle)

    # Decorative Divider
    draw.line([((width // 2) - 80, 380), ((width // 2) + 80, 380)], fill="#236B57", width=4)

    # 4. Service Badges Matrix (Clean Pure Text without missing emoji glyphs)
    services = [
        ("01", "تطوير المواقع والمتاجر الإلكترونية السريعة"),
        ("02", "صناعة الهوية البصرية وتصميم الشعارات الاحترافية"),
        ("03", "وكلاء الذكاء الاصطناعي وأتمتة العمليات اليومية"),
        ("04", "الأنظمة السحابية المخصصة وإدارة الأعمال ERP"),
    ]

    col_w = 700
    box_h = 75
    gap_x = 40
    gap_y = 25
    start_y = 430
    start_x = (width - (col_w * 2 + gap_x)) // 2

    for idx, (num, s) in enumerate(services):
        row = idx // 2
        col = idx % 2
        bx = start_x + col * (col_w + gap_x)
        by = start_y + row * (box_h + gap_y)

        # Draw Card Container
        draw.rounded_rectangle([bx, by, bx + col_w, by + box_h], radius=14, fill="#182A24", outline="#236B57", width=2)
        
        # Draw Service Text
        s_shaped = shape_ar(s)
        sw_item = draw.textlength(s_shaped, font=font_badge)
        draw.text((bx + (col_w - sw_item) // 2, by + 20), s_shaped, fill="#F3F1EA", font=font_badge)

    # 5. Footer Bar
    draw.line([(margin_x + 60, height - margin_y - 120), (width - margin_x - 60, height - margin_y - 120)], fill="#2E343D", width=2)

    footer_left = shape_ar("استشر فريقنا الهندسي الآن لبدء مشروعك")
    draw.text((margin_x + 60, height - margin_y - 80), footer_left, fill="#9CA3AF", font=font_footer)

    draw.text((width - margin_x - 260, height - margin_y - 80), "amancode.tech", fill="#F3F1EA", font=font_footer_bold)

    img.save(output_path, "JPEG", quality=98, subsampling=0)
    print("Clean Arabic Cover generated successfully at:", output_path)
    return output_path

if __name__ == "__main__":
    out = "/home/omar/Desktop/work/aman-core/assets/amancode_facebook_cover.jpg"
    create_facebook_cover(out)
