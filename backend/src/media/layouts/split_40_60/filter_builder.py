"""FFmpeg filter-graph builders for 40/60 Split, Side-by-Side, and Fullscreen 9:16 layouts."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ...ffmpeg import clamp_even, round_to_even

logger = logging.getLogger(__name__)

OUT_W = 1080
OUT_H = 1920


def build_side_by_side_filter(
    width: int,
    height: int,
    divider_x: int,
    face_on_right: bool,
) -> Dict[str, Any]:
    """Build Top-Content / Bottom-Camera layout when stream is split side-by-side."""
    if face_on_right:
        content_x, content_w = 0, round_to_even(divider_x)
        cam_x, cam_w = round_to_even(divider_x), round_to_even(width - divider_x)
    else:
        cam_x, cam_w = 0, round_to_even(divider_x)
        content_x, content_w = round_to_even(divider_x), round_to_even(width - divider_x)

    top_h = 1040
    bottom_h = OUT_H - top_h  # 880

    content_filter = (
        f"crop={content_w}:{height}:{content_x}:0,"
        f"scale={OUT_W}:{top_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        f"pad={OUT_W}:{top_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
    cam_filter = (
        f"crop={cam_w}:{height}:{cam_x}:0,"
        f"scale={OUT_W}:{bottom_h}:flags=lanczos,setsar=1"
    )
    video_filter = (
        f"[0:v]split=2[csrc][msrc];"
        f"[csrc]{content_filter}[top];"
        f"[msrc]{cam_filter}[bottom];"
        f"[top][bottom]vstack=inputs=2[vout]"
    )

    caption_y = round(top_h / OUT_H, 3)
    logger.info(
        "Configured Side-by-Side layout: Content (%d,%d), Camera (%d,%d), CaptionY=%.2f",
        content_w, height, cam_w, height, caption_y,
    )
    return {
        "video_filter": video_filter,
        "mode": "complex",
        "caption_y": caption_y,
        "layout_type": "side_by_side",
    }


def build_corner_40_60_filter(
    width: int,
    height: int,
    webcam: Dict[str, Any],
) -> Dict[str, Any]:
    """Build 40/60 split filter: Top 40% (1080x760) facecam + Bottom 60% (1080x1160) gameplay."""
    top_h = 760
    bottom_h = OUT_H - top_h  # 1160

    is_left = webcam["cx"] < width / 2
    crop_cam_w = round_to_even(int(min(width * 0.35, max(webcam["w"] * 3.5, width * 0.203))))
    crop_cam_h = round_to_even(int(crop_cam_w * top_h / OUT_W))

    cam_x = 0 if is_left else max(0, width - crop_cam_w)

    cam_y = int(webcam["cy"] - crop_cam_h * 0.45)
    face_top = webcam["cy"] - webcam["h"] / 2
    if cam_y > face_top - 20:
        cam_y = int(face_top - 20)
    face_bottom = webcam["cy"] + webcam["h"] / 2
    if cam_y + crop_cam_h < face_bottom + 25:
        cam_y = int(face_bottom + 25 - crop_cam_h)

    cam_x = clamp_even(cam_x, 0, width - crop_cam_w)
    cam_y = clamp_even(cam_y, 0, height - crop_cam_h)

    game_h = height
    game_w = round_to_even(int(game_h * OUT_W / bottom_h))
    if is_left:
        game_x = clamp_even(max(cam_x + crop_cam_w + 10, (width - game_w) // 2), 0, width - game_w)
    else:
        game_x = clamp_even(min(cam_x - game_w - 10, (width - game_w) // 2), 0, width - game_w)

    video_filter = (
        f"[0:v]split=2[camsrc][gamesrc];"
        f"[camsrc]crop={crop_cam_w}:{crop_cam_h}:{cam_x}:{cam_y},"
        f"scale={OUT_W}:{top_h}:flags=lanczos,unsharp=lx=3:ly=3:la=0.6,setsar=1[top];"
        f"[gamesrc]crop={game_w}:{game_h}:{game_x}:0,"
        f"scale={OUT_W}:{bottom_h}:flags=lanczos,setsar=1[bottom];"
        f"[top][bottom]vstack=inputs=2[vout]"
    )

    caption_y = 0.85
    logger.info(
        "Configured Twitch-Matched 40/60 Layout: Webcam on Top (%d,%d at %d,%d -> %dx%d), "
        "Game on Bottom (%d,%d at %d,0 -> %dx%d), CaptionY=%.2f, Zero Gap",
        crop_cam_w, crop_cam_h, cam_x, cam_y, OUT_W, top_h,
        game_w, game_h, game_x, OUT_W, bottom_h,
        caption_y,
    )
    return {
        "video_filter": video_filter,
        "mode": "complex",
        "caption_y": caption_y,
        "layout_type": "twitch_vertical_40_60",
    }


def build_fullscreen_9_16_filter(
    width: int,
    height: int,
    face_cx: float,
) -> Dict[str, Any]:
    """Build universal single-camera / Just Chatting 9:16 vertical crop centered on face."""
    crop_w = round_to_even(int(height * 9 / 16))
    crop_x = clamp_even(int(face_cx - crop_w // 2), 0, width - crop_w)
    video_filter = (
        f"[0:v]crop={crop_w}:{height}:{crop_x}:0,"
        f"scale={OUT_W}:{OUT_H}:flags=lanczos,unsharp=lx=3:ly=3:la=0.5,setsar=1[vout]"
    )
    caption_y = 0.82
    logger.info(
        "Configured Universal Fullscreen 9:16 Layout: crop %dx%d at %d,0 centered on face at x=%d, caption_y=%.2f",
        crop_w, height, crop_x, int(face_cx), caption_y,
    )
    return {
        "video_filter": video_filter,
        "mode": "complex",
        "caption_y": caption_y,
        "layout_type": "fullscreen_vertical",
    }


def build_deterministic_40_60_fallback(
    src_w: int,
    src_h: int,
    corner: str = "top_right",
) -> Dict[str, Any]:
    """Fallback 40/60 vertical split when YuNet detection finds no stationary face."""
    top_h = 760
    bottom_h = 1160
    cam_w = round_to_even(int(src_w * 0.35))
    cam_h = round_to_even(int(cam_w * top_h / OUT_W))
    cam_x = 0 if corner == "top_left" else (src_w - cam_w)
    cam_y = clamp_even(int(src_h * 0.03), 0, src_h - cam_h)

    game_h = src_h
    game_w = round_to_even(int(game_h * OUT_W / bottom_h))
    game_x = clamp_even((src_w - game_w) // 2, 0, src_w - game_w)

    video_filter = (
        f"[0:v]split=2[camsrc][gamesrc];"
        f"[camsrc]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
        f"scale={OUT_W}:{top_h}:flags=lanczos,unsharp=lx=3:ly=3:la=0.6,setsar=1[top];"
        f"[gamesrc]crop={game_w}:{game_h}:{game_x}:0,"
        f"scale={OUT_W}:{bottom_h}:flags=lanczos,setsar=1[bottom];"
        f"[top][bottom]vstack=inputs=2[vout]"
    )
    return {
        "video_filter": video_filter,
        "mode": "complex",
        "caption_y": 0.85,
        "layout_type": f"deterministic_40_60_{corner}",
    }
