"""Dramatic High-CTR Image Alteration, Atmospheric FX, & Spy-Glass Focus Engine."""

from __future__ import annotations

import math
import random
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

FaceBox = Tuple[float, float, float, float]
Point = Tuple[float, float]


def infer_scene_theme(hook_title: str) -> str:
    """Infer dramatic visual FX theme from hook title (police / fire / shock)."""
    low = (hook_title or "").lower()
    if any(k in low for k in ("cop", "cops", "police", "five star", "5 star", "gta", "flee", "arrest", "chase", "swat")):
        return "police"
    if any(k in low for k in ("fire", "burn", "explod", "crash", "wreck", "rage", "lost it", "desk", "smashed", "destroy")):
        return "fire"
    return "shock"


def enhance_face_and_depth(bgr: np.ndarray, face_box: Optional[FaceBox]) -> np.ndarray:
    """Sharpen & brighten facial features while softly defocusing background clutter."""
    out = bgr.copy()
    h, w = out.shape[:2]

    if face_box is not None:
        fx, fy, fw, fh = face_box
        fcx, fcy = fx + fw / 2.0, fy + fh / 2.0

        # 1. Local CLAHE facial clarity + eye/skin pop inside upper webcam half
        pad_x = int(fw * 0.55)
        pad_y = int(fh * 0.55)
        x1, y1 = max(0, int(fx - pad_x)), max(0, int(fy - pad_y))
        x2, y2 = min(w, int(fx + fw + pad_x)), min(h, int(fy + fh + pad_y))
        if x2 > x1 + 10 and y2 > y1 + 10:
            roi = out[y1:y2, x1:x2]
            lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
            l_chan, a_chan, b_chan = cv2.split(lab)
            mean_l = float(l_chan.mean())
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(6, 6))
            l_boost = clahe.apply(l_chan)
            # Only lift dark webcams; prevent blowing out bright highlights
            if mean_l < 125.0:
                l_boost = np.clip(l_boost.astype(np.float32) * 1.06 + 4.0, 0, 245).astype(np.uint8)
            popped_roi = cv2.cvtColor(cv2.merge([l_boost, a_chan, b_chan]), cv2.COLOR_LAB2BGR)
            out[y1:y2, x1:x2] = cv2.addWeighted(popped_roi, 0.55, roi, 0.45, 0)

        # 2. Subtle top-half bokeh/motion separation outside the streamer's body
        if fcy < 760:
            top = out[0:760, 0:1080]
            blurred_top = cv2.GaussianBlur(top, (19, 19), 0)
            yy, xx = np.mgrid[0:760, 0:1080]
            rx = max(140.0, fw * 1.65)
            ry = max(180.0, fh * 2.10)
            dist = ((xx - fcx) / rx) ** 2 + ((yy - (fcy + fh * 0.25)) / ry) ** 2
            alpha = np.clip((dist - 0.85) / 1.35, 0.0, 0.68).astype(np.float32)[..., None]
            out[0:760, 0:1080] = (top.astype(np.float32) * (1.0 - alpha) + blurred_top.astype(np.float32) * alpha).astype(np.uint8)

    return out


def apply_cinematic_hdr_grade(rgb_img: Image.Image) -> Image.Image:
    """Apply punchy YouTube HDR color grading: vivid saturation, contrast S-curve, crisp micro-detail."""
    img = ImageEnhance.Color(rgb_img).enhance(1.42)
    img = ImageEnhance.Contrast(img).enhance(1.22)
    img = ImageEnhance.Sharpness(img).enhance(1.32)

    arr = np.asarray(img).astype(np.float32) / 255.0
    # Gentle S-curve contrast + warm highlight lift
    arr = np.clip(arr * arr * (3.0 - 2.0 * arr) * 0.28 + arr * 0.72, 0.0, 1.0)
    # Dark edge vignette for instant mobile eye centering
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx - w / 2.0) / (w / 2.0)
    ny = (yy - h / 2.0) / (h / 2.0)
    vig = 1.0 - np.clip((nx * nx * 0.55 + ny * ny * 0.45 - 0.35) * 0.45, 0.0, 0.42)
    arr *= vig[..., None]
    return Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))


def apply_atmospheric_fx(
    img_rgb: Image.Image,
    theme: str,
    seed_key: str = "",
    face_box: Optional[FaceBox] = None,
) -> Image.Image:
    """Alter thumbnail mood with glowing edge flares, dramatic rays, and fiery/electric particles."""
    rgba = img_rgb.convert("RGBA")
    w, h = rgba.size
    fx_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fx_layer)

    rng = random.Random(hash(seed_key or theme) & 0xFFFFFFFF)

    if theme == "police":
        # Red siren left glow + Electric Blue siren right glow
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((-220, -140, 420, 560), fill=(255, 25, 45, 145))
        gd.ellipse((w - 420, -140, w + 220, 560), fill=(20, 115, 255, 155))
        gd.ellipse((-240, 1150, 320, 1780), fill=(255, 20, 40, 105))
        gd.ellipse((w - 320, 1150, w + 240, 1780), fill=(20, 115, 255, 105))
        glow = glow.filter(ImageFilter.GaussianBlur(95))
        rgba = Image.alpha_composite(rgba, glow)
    elif theme == "fire":
        # Warm crimson & molten gold edge fire glow
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((-200, 1300, w + 200, h + 320), fill=(255, 95, 10, 150))
        gd.ellipse((-180, -140, 360, 460), fill=(255, 45, 15, 115))
        gd.ellipse((w - 360, -140, w + 180, 460), fill=(255, 160, 15, 115))
        glow = glow.filter(ImageFilter.GaussianBlur(90))
        rgba = Image.alpha_composite(rgba, glow)
    else:
        # High-voltage red + gold rim highlights
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((-200, -120, 380, 480), fill=(255, 30, 50, 125))
        gd.ellipse((w - 380, -120, w + 200, 480), fill=(255, 210, 0, 115))
        glow = glow.filter(ImageFilter.GaussianBlur(90))
        rgba = Image.alpha_composite(rgba, glow)

    # Radial comic speed-lines around outer perimeter (never cluttering center face)
    cx, cy = w // 2, 420
    for i in range(28):
        angle = (2 * math.pi * i) / 28.0 + rng.uniform(-0.04, 0.04)
        r_inner = rng.randint(430, 520)
        r_outer = 1150
        x0 = cx + r_inner * math.cos(angle)
        y0 = cy + r_inner * math.sin(angle)
        x1 = cx + r_outer * math.cos(angle)
        y1 = cy + r_outer * math.sin(angle)
        col = (255, 240, 120, 55) if i % 2 == 0 else (255, 60, 60, 48)
        draw.line([(x0, y0), (x1, y1)], fill=col, width=rng.randint(3, 7))

    # Fiery sparks / glowing embers in lower & edge areas (strictly outside streamer face box!)
    spark_count = 34 if theme == "fire" else 20
    for _ in range(spark_count):
        sx = rng.randint(20, w - 20)
        sy = rng.randint(780, h - 80) if rng.random() < 0.72 else rng.randint(20, 300)
        if face_box is not None:
            fx, fy, fw, fh = face_box
            if (fx - 45) <= sx <= (fx + fw + 45) and (fy - 45) <= sy <= (fy + fh + 45):
                continue
        sr = rng.randint(3, 8)
        scol = (255, rng.randint(150, 245), 35, rng.randint(145, 230))
        draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=scol)

    fx_blurred = fx_layer.filter(ImageFilter.GaussianBlur(1.2))
    rgba = Image.alpha_composite(rgba, fx_blurred)
    return rgba.convert("RGB")


def draw_spyglass_zoom_callout(
    img_rgb: Image.Image,
    hotspot: Point,
    text_band_top: int,
    text_band_bottom: int,
    face_box: Optional[FaceBox] = None,
) -> Tuple[Image.Image, Point]:
    """Create a signature YouTube 1.48x magnified circular callout & target reticle around climax hotspot.

    Returns (updated_image, callout_center_point) so arrows can point right at the climax target.
    """
    w, h = img_rgb.size
    hx, hy = hotspot
    max_y = 1540.0
    if face_box is not None and (face_box[1] + face_box[3] / 2.0) >= 900.0:
        max_y = max(text_band_bottom + 140.0, face_box[1] - 240.0)

    # Clamp hotspot cleanly inside lower action half away from captions/text band/bottom face
    hx = max(210.0, min(w - 210.0, hx))
    hy = max(float(max(1060, text_band_bottom + 110)), min(max_y, hy))

    radius = 120
    # Target circle around hotspot
    src_r = int(radius / 1.48)
    sx1, sy1 = max(0, int(hx - src_r)), max(0, int(hy - src_r))
    sx2, sy2 = min(w, int(hx + src_r)), min(h, int(hy + src_r))
    if sx2 - sx1 < 40 or sy2 - sy1 < 40:
        return img_rgb, (hx, hy)

    crop_patch = img_rgb.crop((sx1, sy1, sx2, sy2)).resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)
    crop_patch = ImageEnhance.Contrast(crop_patch).enhance(1.16)
    crop_patch = ImageEnhance.Sharpness(crop_patch).enhance(1.25)

    # Place magnified bubble cleanly on the OPPOSITE side from where the arrow will enter, below hotspot
    offset_x = -250 if hx > w * 0.50 else 250
    lx = int(max(radius + 36, min(w - radius - 36, hx + offset_x)))
    ly = int(max(text_band_bottom + radius + 55, min(max_y - 20.0, hy + 120)))

    rgba = img_rgb.convert("RGBA")

    # 1. Draw glowing red focus ring right over the actual hotspot
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    ring_r = 72
    od.ellipse((hx - ring_r - 6, hy - ring_r - 6, hx + ring_r + 6, hy + ring_r + 6), outline=(0, 0, 0, 220), width=14)
    od.ellipse((hx - ring_r, hy - ring_r, hx + ring_r, hy + ring_r), outline=(255, 25, 45, 255), width=9)
    # Connector line between focus ring and zoomed spyglass bubble
    od.line([(hx, hy), (lx, ly)], fill=(0, 0, 0, 210), width=11)
    od.line([(hx, hy), (lx, ly)], fill=(255, 235, 0, 245), width=5)

    # 2. Drop shadow for spyglass lens
    od.ellipse((lx - radius - 8, ly - radius - 2, lx + radius + 14, ly + radius + 18), fill=(0, 0, 0, 190))
    rgba = Image.alpha_composite(rgba, overlay)

    # 3. Circular mask + paste zoomed patch
    mask = Image.new("L", (radius * 2, radius * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, radius * 2, radius * 2), fill=255)
    rgba.paste(crop_patch.convert("RGBA"), (lx - radius, ly - radius), mask)

    # 4. Crisp white inner border + neon red outer border around spyglass lens
    ring_draw = ImageDraw.Draw(rgba)
    ring_draw.ellipse((lx - radius, ly - radius, lx + radius, ly + radius), outline=(255, 255, 255, 255), width=10)
    ring_draw.ellipse((lx - radius - 4, ly - radius - 4, lx + radius + 4, ly + radius + 4), outline=(255, 25, 45, 255), width=6)

    return rgba.convert("RGB"), (float(hx), float(hy))


def draw_curved_neon_arrow(
    draw: ImageDraw.Draw,
    start: Point,
    end: Point,
    color: Tuple[int, int, int] = (255, 25, 45),
    width: int = 18,
) -> None:
    """Draw a chunky, glossy 3D YouTube curved arrow with black outline & yellow core."""
    x0, y0 = start
    x1, y1 = end
    cx = (x0 + x1) / 2.0 + (y1 - y0) * 0.28
    cy = (y0 + y1) / 2.0 - (x1 - x0) * 0.28

    points = []
    for t_step in range(28):
        t = t_step / 27.0
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
        points.append((x, y))

    draw.line([(px + 6, py + 8) for px, py in points], fill=(0, 0, 0), width=width + 16)
    draw.line(points, fill=(0, 0, 0), width=width + 12)
    draw.line(points, fill=color, width=width)
    draw.line(points, fill=(255, 240, 80), width=max(5, width - 8))

    dx = x1 - points[-4][0]
    dy = y1 - points[-4][1]
    angle = math.atan2(dy, dx)
    arrow_len = 48
    arrow_angle = math.radians(34)

    p1 = (x1 - arrow_len * math.cos(angle - arrow_angle), y1 - arrow_len * math.sin(angle - arrow_angle))
    p2 = (x1 - arrow_len * math.cos(angle + arrow_angle), y1 - arrow_len * math.sin(angle + arrow_angle))
    draw.polygon([(end[0] + 6, end[1] + 8), (p1[0] + 6, p1[1] + 8), (p2[0] + 6, p2[1] + 8)], fill=(0, 0, 0))
    draw.polygon([end, p1, p2], fill=color)

    inner_p1 = (x1 - (arrow_len - 14) * math.cos(angle - arrow_angle * 0.68), y1 - (arrow_len - 14) * math.sin(angle - arrow_angle * 0.68))
    inner_p2 = (x1 - (arrow_len - 14) * math.cos(angle + arrow_angle * 0.68), y1 - (arrow_len - 14) * math.sin(angle + arrow_angle * 0.68))
    draw.polygon([end, inner_p1, inner_p2], fill=(255, 250, 170))


def draw_vector_lightning(draw: ImageDraw.Draw, x: float, y: float, size: float = 34) -> None:
    """Draw a crisp vector lightning bolt icon (replaces broken Unicode glyphs)."""
    pts = [
        (x + size * 0.45, y),
        (x + size * 0.05, y + size * 0.55),
        (x + size * 0.42, y + size * 0.55),
        (x + size * 0.22, y + size),
        (x + size * 0.85, y + size * 0.40),
        (x + size * 0.48, y + size * 0.40),
    ]
    draw.polygon(pts, fill=(255, 235, 0), outline=(0, 0, 0))
