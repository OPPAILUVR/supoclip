"""High-CTR 9:16 Viral Thumbnail Compositor for SupoClip."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image, ImageDraw

from .frame_selector import extract_best_climax_composite
from .headline_engine import (
    CANDIDATE_FONTS,
    _get_best_font,
    _synthesize_thumbnail_headline,
    draw_corner_viral_stamp,
    render_headline_and_badge,
)
from .visual_fx import (
    apply_atmospheric_fx,
    apply_cinematic_hdr_grade,
    draw_curved_neon_arrow,
    draw_spyglass_zoom_callout,
    enhance_face_and_depth,
    infer_scene_theme,
)

logger = logging.getLogger("ThumbnailGenerator")


def _apply_text_scrim(img: Image.Image, target_text_y: int) -> Image.Image:
    """Render soft cinematic gradient behind the headline divider band for 10:1 legibility."""
    gradient_overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(gradient_overlay)
    grad_top = max(0, target_text_y - 80)
    grad_bottom = min(1920, target_text_y + 420)
    for y_pos in range(grad_top, grad_bottom):
        rel = (y_pos - grad_top) / max(1, grad_bottom - grad_top)
        alpha = int(225 * math.sin(rel * math.pi))
        g_draw.line([(0, y_pos), (1080, y_pos)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), gradient_overlay).convert("RGB")


def generate_viral_thumbnail(
    video_path: Path,
    hook_title: str,
    streamer_name: str = "",
    output_path: Optional[Path] = None,
    badge_override: Optional[str] = None,
) -> Path:
    """Generate a high-CTR altered/composited 9:16 thumbnail (1080x1920) + 16:9 companion.

    Pipeline:
      1. Dual-Frame Climax Composite (Zoomed Peak Face Reaction + Peak Action Scene)
      2. Facial clarity boost + background bokeh separation
      3. Cinematic HDR color grade + scene-matched dramatic atmosphere (siren / fire / neon FX)
      4. Action-targeted Spy-Glass circular 1.48x zoom callout + 3D glossy arrow
      5. Oversized multi-color 3D typography + vector badge + corner live stamp (zero tofu glyphs!)
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if output_path is None:
        output_path = video_path.parent / f"{video_path.stem}_thumb.jpg"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Dual-frame peak face + peak action extraction & composite
    composite_bgr, _, face_box, action_hotspot = extract_best_climax_composite(video_path)

    # 2. Local expression clarity + soft bokeh separation around face
    enhanced_bgr = enhance_face_and_depth(composite_bgr, face_box)
    img = Image.fromarray(cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB))

    # 3. Cinematic HDR grade + atmospheric dramatic flares (police siren / fire embers / electric burst)
    theme = infer_scene_theme(hook_title)
    img = apply_cinematic_hdr_grade(img)
    img = apply_atmospheric_fx(img, theme=theme, seed_key=hook_title, face_box=face_box)

    # 4. Compute safe text band Y (middle divider below top webcam, or top if cam is low)
    lines, default_badge = _synthesize_thumbnail_headline(hook_title, streamer_name)
    badge = badge_override or default_badge

    if face_box:
        fx, fy, fw, fh = face_box
        face_center_y = fy + fh / 2.0
        target_text_y = max(720, min(830, int(fy + fh + 24))) if face_center_y < 720 else 180
    else:
        target_text_y = 740
    target_text_y = min(980, max(160, target_text_y))

    # 5. Dark contrast scrim behind typography
    img = _apply_text_scrim(img, target_text_y)

    # 6. Circular Spy-Glass 1.48x Zoom Callout pointing at the real action hotspot
    approx_band_bottom = target_text_y + 340
    img, callout_target = draw_spyglass_zoom_callout(
        img,
        hotspot=action_hotspot,
        text_band_top=target_text_y - 40,
        text_band_bottom=approx_band_bottom,
        face_box=face_box,
    )

    # 7. Render crisp vector-icon Typography + Corner Stamp
    img, band_top, band_bottom = render_headline_and_badge(img, lines, badge, target_text_y)
    stamp_label = "5-STAR CHASE" if theme == "police" else ("RAGE CAM" if theme == "fire" else "CAUGHT LIVE")
    img = draw_corner_viral_stamp(img, label=stamp_label)

    # 8. Draw chunky curved arrow directly into the climax hotspot (never pointing at empty space!)
    draw = ImageDraw.Draw(img)
    hx, hy = callout_target
    arrow_start_x = 140.0 if hx > 540 else 940.0
    arrow_start_y = float(min(1820, max(band_bottom + 30, hy - 220)))
    try:
        draw_curved_neon_arrow(draw, (arrow_start_x, arrow_start_y), (hx, hy), color=(255, 25, 45), width=18)
    except Exception as arrow_err:
        logger.debug("Arrow callout notice: %s", arrow_err)

    # 9. Save Master 9:16 Thumbnail (1080x1920) + Companion 16:9 (1280x720)
    img.save(str(output_path), "JPEG", quality=96, optimize=True)
    logger.info("Generated high-CTR altered 9:16 viral thumbnail at: %s (theme=%s)", output_path, theme)

    landscape_path = output_path.parent / f"{output_path.stem}_16x9.jpg"
    try:
        c_y = max(0, min(1920 - 608, target_text_y - 120))
        land_crop = img.crop((0, c_y, 1080, c_y + 608)).resize((1280, 720), Image.Resampling.LANCZOS)
        land_crop.save(str(landscape_path), "JPEG", quality=92)
    except Exception as land_err:
        logger.debug("Could not generate landscape companion thumbnail: %s", land_err)

    return output_path


__all__ = [
    "CANDIDATE_FONTS",
    "_get_best_font",
    "_synthesize_thumbnail_headline",
    "generate_viral_thumbnail",
]
