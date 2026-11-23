#!/usr/bin/env python3
"""
Viral Thumbnail Generator Service for SupoClip.
Empirically engineered to maximize Click-Through Rate (CTR) on YouTube Shorts and video feeds:
1. CV-based Peak Emotion / Climax frame selection (samples the 35%-60% midpoint climax).
2. Vibrance & Contrast color grading (+25% saturation, +15% contrast).
3. High-CTR Impact typography with heavy 10px black stroke and drop-shadow.
4. Red accent reaction pill badge ("💥 INSTANT REGRET 💀", "🚨 CAUGHT IN 4K 😱").
5. Produces both 9:16 vertical (1080x1920) and 16:9 landscape thumbnails.
"""

import os
import re
import cv2
import logging
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

logger = logging.getLogger("ThumbnailGenerator")

# Available high-impact fonts on macOS / Linux
CANDIDATE_FONTS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
]

REACTION_BADGES = [
    "💥 INSTANT KARMA 💀",
    "🚨 CAUGHT IN 4K 😱",
    "⚠️ HE REALLY DID THIS?!",
    "🔥 NO WAY THIS HAPPENED 😭",
    "❌ BIGGEST REGRET EVER 💀",
    "🤯 THE EXACT SECOND 😱"
]


def _get_best_font(size: int) -> ImageFont.FreeTypeFont:
    for font_path in CANDIDATE_FONTS:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _synthesize_thumbnail_headline(hook_title: str) -> Tuple[List[str], str]:
    """
    Transforms a sentence hook_title into a punchy 2-4 word thumbnail headline
    and an accompanying emotional badge.
    """
    clean = re.sub(r"[#@\-_:;!?]", " ", hook_title).strip()
    words = clean.split()
    
    # Check for known viral trigger words
    lower = hook_title.lower()
    badge = REACTION_BADGES[0]
    
    if "regret" in lower or "mistake" in lower or "karma" in lower or "destroyed" in lower or "demolished" in lower:
        badge = "💥 INSTANT REGRET 💀"
    elif "caught" in lower or "4k" in lower or "secret" in lower or "exposed" in lower:
        badge = "🚨 CAUGHT IN 4K 😱"
    elif "insane" in lower or "crazy" in lower or "broke" in lower:
        badge = "⚠️ HE REALLY DID THIS?! 🤯"
    elif "exact second" in lower or "fell apart" in lower or "realizes" in lower:
        badge = "🤯 THE EXACT SECOND 😭"

    # Distill words into 2-4 punchy words
    if len(words) <= 3:
        lines = [" ".join(words).upper()]
    elif len(words) <= 5:
        mid = len(words) // 2
        lines = [" ".join(words[:mid]).upper(), " ".join(words[mid:]).upper()]
    else:
        # Extract the highest energy action words
        core_words = [w for w in words if len(w) > 3 and w.lower() not in {"that", "when", "this", "with", "into", "from", "then"}]
        if len(core_words) >= 4:
            lines = [" ".join(core_words[:2]).upper(), " ".join(core_words[2:4]).upper()]
        elif len(core_words) >= 2:
            lines = [" ".join(core_words[:2]).upper()]
        else:
            lines = [" ".join(words[:3]).upper(), " ".join(words[3:6]).upper()]

    # Format with punctuation for maximum CTR curiosity
    if len(lines) > 0 and not lines[-1].endswith(("?!", "?", "!", "💀")):
        lines[-1] += "?!"

    return lines, badge


def extract_best_climax_frame(video_path: Path) -> Tuple[np.ndarray, float]:
    """
    Uses OpenCV to find the sharpest, most emotionally charged frame
    in the 35%-60% midpoint climax window.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    # Empirical climax window: 35% to 60%
    start_f = max(0, int(total_frames * 0.35))
    end_f = min(total_frames - 1, int(total_frames * 0.60))
    if start_f >= end_f:
        start_f = 0
        end_f = total_frames - 1

    # Load Haar cascade
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    best_frame = None
    best_score = -1.0
    best_sec = 0.0

    step = max(1, int(fps * 0.35))  # Sample every ~0.35 seconds

    for f_idx in range(start_f, end_f, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Sharpness via Laplacian variance
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

        # 2. Face detection
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))
        face_score = len(faces) * 500.0
        if len(faces) > 0:
            max_area = max(w * h for (x, y, w, h) in faces)
            face_score += max_area * 0.5

        # 3. Motion / Intensity score
        score = face_score + sharpness
        if score > best_score:
            best_score = score
            best_frame = frame.copy()
            best_sec = f_idx / fps

    cap.release()

    if best_frame is None:
        # Fallback to middle frame
        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        ret, best_frame = cap.read()
        cap.release()
        best_sec = duration / 2.0

    logger.info("Selected optimal climax thumbnail frame at %.2fs (score: %.1f)", best_sec, best_score)
    return best_frame, best_sec


def generate_viral_thumbnail(
    video_path: Path,
    hook_title: str,
    streamer_name: str = "",
    output_path: Optional[Path] = None,
    badge_override: Optional[str] = None
) -> Path:
    """
    Generates a viral thumbnail image from video_path.
    Returns the Path to the generated thumbnail.jpg.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if output_path is None:
        output_path = video_path.parent / f"{video_path.stem}_thumb.jpg"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Extract best climax frame
    frame, timestamp = extract_best_climax_frame(video_path)
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb_frame)

    # 2. Scale / Conform to 1080x1920 canvas
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920), Image.Resampling.LANCZOS)

    # 3. Boost Color Grading (Saturation +25%, Contrast +15%)
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # 4. Synthesize Headlines & Badges
    lines, default_badge = _synthesize_thumbnail_headline(hook_title)
    badge = badge_override or default_badge

    draw = ImageDraw.Draw(img)

    # 5. Render Main Headline Text (Impact Bold, Electric Yellow, 10px Stroke)
    font_size = 105 if len(lines) > 1 else 125
    main_font = _get_best_font(font_size)
    
    text_color = (255, 230, 0)      # Electric Yellow (#FFE600)
    stroke_color = (0, 0, 0)         # Pitch Black Stroke
    stroke_width = 10
    shadow_offset = 12

    # Upper third safe zone (Y: 260 - 450)
    cur_y = 280
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=main_font, stroke_width=stroke_width)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = (1080 - text_w) // 2

        # Draw deep shadow
        draw.text(
            (text_x + shadow_offset, cur_y + shadow_offset),
            line,
            font=main_font,
            fill=(0, 0, 0, 220),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0)
        )
        # Draw main text
        draw.text(
            (text_x, cur_y),
            line,
            font=main_font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color
        )
        cur_y += text_h + 25

    # 6. Render Reaction Pill Badge (Red #E50914 with white text & outline)
    badge_font = _get_best_font(44)
    b_box = draw.textbbox((0, 0), badge, font=badge_font)
    bw = b_box[2] - b_box[0]
    bh = b_box[3] - b_box[1]
    bx = (1080 - bw) // 2
    by = cur_y + 15

    pad_x, pad_y = 35, 14
    pill_box = [bx - pad_x, by - pad_y, bx + bw + pad_x, by + bh + pad_y]
    draw.rounded_rectangle(
        pill_box,
        radius=25,
        fill=(229, 9, 20),           # Viral YouTube Red
        outline=(255, 255, 255),       # Crisp White Outline
        width=4
    )
    draw.text((bx, by), badge, font=badge_font, fill=(255, 255, 255))

    # 7. Save High-Quality JPEG
    img.save(str(output_path), "JPEG", quality=95, optimize=True)
    logger.info("Successfully generated viral thumbnail at: %s", output_path)

    # Also save 16:9 version for desktop previews
    landscape_path = output_path.parent / f"{output_path.stem}_16x9.jpg"
    try:
        # Crop center 1080x608 and resize to 1280x720
        landscape_crop = img.crop((0, 300, 1080, 300 + 608)).resize((1280, 720), Image.Resampling.LANCZOS)
        landscape_crop.save(str(landscape_path), "JPEG", quality=92)
    except Exception as land_err:
        logger.debug("Could not generate landscape companion thumbnail: %s", land_err)

    return output_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python thumbnail_generator.py <video_path> [hook_title]")
        sys.exit(1)

    vid = Path(sys.argv[1])
    hook = sys.argv[2] if len(sys.argv) > 2 else vid.stem
    out = generate_viral_thumbnail(vid, hook)
    print(f"Generated: {out}")
