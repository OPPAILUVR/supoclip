"""High-CTR Hook Headline Synthesizer, Bundled Font Loader, & Vector Badge Renderer."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

from .visual_fx import draw_vector_lightning

FONTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fonts"

CANDIDATE_FONTS = [
    str(FONTS_DIR / "THEBOLDFONT.ttf"),
    str(FONTS_DIR / "ArchivoBlack-Regular.ttf"),
    str(FONTS_DIR / "Anton-Regular.ttf"),
    str(FONTS_DIR / "Bangers-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _get_best_font(size: int) -> ImageFont.FreeTypeFont:
    for font_path in CANDIDATE_FONTS:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _strip_streamer_prefix(words: List[str], streamer_name: str) -> List[str]:
    if not words:
        return words
    s_norm = re.sub(r"[^a-z0-9]", "", (streamer_name or "").lower())
    first_norm = re.sub(r"[^a-z0-9]", "", words[0].lower())
    if s_norm and first_norm and (first_norm == s_norm or first_norm.startswith(s_norm)):
        return words[1:] if len(words) > 2 else words
    return words


def _synthesize_thumbnail_headline(hook_title: str, streamer_name: str = "") -> Tuple[List[str], str]:
    """Transform hook_title into a glyph-safe, ultra-punchy 2-line click-forcing hook + badge.

    Strictly avoids raw Unicode emojis that render as broken boxes ('□□') in display fonts.
    """
    raw = hook_title or ""
    lower = raw.lower()

    # Determine badge text by emotional archetype (pure ASCII + vector icon rendered separately)
    if any(k in lower for k in ("five star", "5 star", "cop", "cops", "police", "arrest", "swat")):
        badge = "5-STAR CHAOS"
    elif any(k in lower for k in ("terrified", "scared", "horror", "jumpscare", "fear", "demon", "whale")):
        badge = "INSTANT PANIC"
    elif any(k in lower for k in ("lost his mind", "loses it", "rage", "desk", "scream", "broke", "destroy", "demolish")):
        badge = "UNHINGED RAGE"
    elif any(k in lower for k in ("regret", "mistake", "karma", "fell apart", "wrong", "too late")):
        badge = "INSTANT REGRET"
    elif any(k in lower for k in ("exposed", "caught", "secret", "cheating", "4k", "truth")):
        badge = "CAUGHT IN 4K"
    elif any(k in lower for k in ("gta", "insane", "impossible", "clutch", "glitch")):
        badge = "NO WAY THIS HAPPENED"
    else:
        badge = "WAIT TILL END"

    # Extract specific action/object words so EVERY thumbnail reflects the actual moment!
    clean_words = re.sub(r"[#@\-_:;!?\"']", " ", raw).split()
    stop_words = {
        "that", "this", "with", "from", "into", "the", "and", "about", "what",
        "when", "after", "while", "during", "over", "under", "eureka", "moment",
        "live", "stream", "video", "clip", "here", "there", "really", "actually",
        "as", "in", "on", "to", "for", "of", "at", "by", "is", "are", "was", "were",
        "his", "her", "their", "our", "just", "then", "than", "an", "a",
    }
    meaningful = [w.upper() for w in clean_words if len(w) > 1 and w.lower() not in stop_words]
    meaningful = _strip_streamer_prefix(meaningful, streamer_name)

    if len(meaningful) >= 4:
        # Prefer last high-impact words if opening verb was generic, or pair key subject+climax
        line1 = " ".join(meaningful[:2])
        line2 = " ".join(meaningful[-2:]) + "!"
        lines = [line1, line2]
    elif len(meaningful) == 3:
        lines = [meaningful[0], f"{meaningful[1]} {meaningful[2]}!"]
    elif len(meaningful) == 2:
        lines = [meaningful[0], f"{meaningful[1]}!"]
    elif len(meaningful) == 1:
        lines = ["NO WAY...", f"{meaningful[0]}!"]
    else:
        lines = ["WAIT TILL", "THE END!"]

    # Ensure lines stay compact enough to render huge (max 14 chars per line ideal)
    if len(lines) == 2 and len(lines[0]) > 15:
        lines[0] = " ".join(lines[0].split()[:2])
    if len(lines) == 2 and len(lines[1]) > 15:
        lines[1] = " ".join(lines[1].split()[:2]).rstrip("!") + "!"

    return lines, badge


def draw_corner_viral_stamp(img: Image.Image, label: str = "CAUGHT LIVE") -> Image.Image:
    """Add a punchy slightly tilted top-left crimson stamp ribbon for instant scroll-stop."""
    rgba = img.convert("RGBA")
    stamp = Image.new("RGBA", (420, 120), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    font = _get_best_font(36)
    bbox = sd.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    box_w = tw + 68
    box_h = th + 28
    # Shadow
    sd.rounded_rectangle([14, 14, 14 + box_w, 14 + box_h], radius=14, fill=(0, 0, 0, 210))
    # Bright crimson ribbon with crisp white border
    sd.rounded_rectangle([8, 8, 8 + box_w, 8 + box_h], radius=14, fill=(235, 16, 32, 248), outline=(255, 255, 255, 255), width=4)
    # Red/white live indicator dot
    sd.ellipse((24, 8 + box_h // 2 - 8, 40, 8 + box_h // 2 + 8), fill=(255, 235, 0, 255))
    sd.text((52, 8 + (box_h - th) // 2 - bbox[1]), label, font=font, fill=(255, 255, 255, 255))

    rotated = stamp.rotate(5.0, expand=True, resample=Image.Resampling.BICUBIC)
    rgba.paste(rotated, (26, 26), rotated)
    return rgba.convert("RGB")


def render_headline_and_badge(
    img: Image.Image,
    lines: List[str],
    badge: str,
    target_text_y: int,
) -> Tuple[Image.Image, int, int]:
    """Render dark spotlight band + oversized 3D Impact typography + vector-icon badge pill.

    Returns (updated_image, text_band_top, text_band_bottom).
    """
    draw = ImageDraw.Draw(img)

    # Fit font dynamically so longest line always stays nicely inside [48..1032] width
    max_text_w = 960
    font_size = 128 if len(lines) > 1 else 148
    font = _get_best_font(font_size)
    while font_size > 72:
        font = _get_best_font(font_size)
        widest = max(draw.textbbox((0, 0), ln, font=font, stroke_width=15)[2] for ln in lines)
        if widest <= max_text_w:
            break
        font_size -= 6

    stroke_w = max(11, font_size // 8)
    shadow_offset = max(10, font_size // 10)

    # Line 1 = Polar White, Line 2 = Electric Gold
    colors = [(255, 255, 255), (255, 230, 0)]
    cur_y = target_text_y

    for idx, line in enumerate(lines):
        line_color = colors[min(idx, len(colors) - 1)]
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_w)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (1080 - tw) // 2 - bbox[0]

        # Deep 3D hard drop shadow
        draw.text(
            (tx + shadow_offset, cur_y + shadow_offset - bbox[1]),
            line,
            font=font,
            fill=(0, 0, 0),
            stroke_width=stroke_w + 5,
            stroke_fill=(0, 0, 0),
        )
        # Main bold text with pitch-black outline
        draw.text(
            (tx, cur_y - bbox[1]),
            line,
            font=font,
            fill=line_color,
            stroke_width=stroke_w,
            stroke_fill=(0, 0, 0),
        )
        cur_y += th + 20

    # Badge Pill with Vector Lightning Icons (no Unicode tofu boxes!)
    badge_font = _get_best_font(44)
    b_box = draw.textbbox((0, 0), badge, font=badge_font)
    bw = b_box[2] - b_box[0]
    bh = b_box[3] - b_box[1]
    icon_sz = 34
    gap = 16
    total_inner_w = icon_sz + gap + bw + gap + icon_sz

    bx = (1080 - total_inner_w) // 2
    by = cur_y + 16
    pad_x, pad_y = 34, 16
    pill_box = [bx - pad_x, by - pad_y, bx + total_inner_w + pad_x, by + bh + pad_y]

    draw.rounded_rectangle([p + 8 for p in pill_box], radius=28, fill=(0, 0, 0))
    draw.rounded_rectangle(
        pill_box,
        radius=28,
        fill=(225, 12, 24),
        outline=(255, 255, 255),
        width=5,
    )

    draw_vector_lightning(draw, bx, by + (bh - icon_sz) / 2.0, size=icon_sz)
    draw.text((bx + icon_sz + gap - b_box[0], by - b_box[1]), badge, font=badge_font, fill=(255, 255, 255))
    draw_vector_lightning(draw, bx + icon_sz + gap + bw + gap, by + (bh - icon_sz) / 2.0, size=icon_sz)

    band_top = max(0, target_text_y - 55)
    band_bottom = min(1920, int(pill_box[3] + 24))
    return img, band_top, band_bottom
