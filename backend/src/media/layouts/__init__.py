"""Unified Vertical Clip Layout Dispatcher (`40_60` Split vs `crop` Top-Down Blur)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from .crop_blur import build_crop_blur_layout
from .split_40_60 import build_deterministic_40_60_fallback, detect_streamer_layout

logger = logging.getLogger(__name__)


def build_live_clip_layout(
    clip_format: str,
    video_path: Path,
    src_w: int,
    src_h: int,
    streamer_name: str = "streamer",
) -> Dict[str, Any]:
    """Resolve FFmpeg vertical layout filter for a live clip based on user format choice.

    - 'crop': Top-Down Blur ambient canvas (skips facecam split detection).
    - '40_60' (default): Universal facecam/side-by-side 40/60 split with deterministic fallback.
    """
    if clip_format == "crop":
        layout = build_crop_blur_layout()
        logger.info("Applied Crop (Top-Down Blur) layout for %s (caption_y=%.2f)", streamer_name, layout["caption_y"])
        return layout

    detected = detect_streamer_layout(video_path, src_w, src_h)
    if detected:
        logger.info(
            "Applied %s layout for %s (caption_y=%.2f)",
            detected.get("layout_type", "custom"),
            streamer_name,
            detected.get("caption_y", 0.85),
        )
        return detected

    fallback = build_deterministic_40_60_fallback(src_w, src_h, corner="top_right")
    logger.info(
        "Applied deterministic 40/60 vertical fallback for %s (caption_y=%.2f)",
        streamer_name,
        fallback["caption_y"],
    )
    return fallback


__all__ = [
    "build_live_clip_layout",
    "build_crop_blur_layout",
    "detect_streamer_layout",
    "build_deterministic_40_60_fallback",
]
