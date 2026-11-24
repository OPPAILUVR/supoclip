"""Backwards-compatible facade for 40/60 Split & Streamer Layout detection.

Implementation now lives in:
  - backend/src/media/layouts/split_40_60/detector.py
  - backend/src/media/layouts/split_40_60/filter_builder.py
  - backend/src/media/layouts/crop_blur/filter_builder.py
"""

from .layouts.split_40_60 import (
    OUT_H,
    OUT_W,
    build_corner_40_60_filter,
    build_deterministic_40_60_fallback,
    build_fullscreen_9_16_filter,
    build_side_by_side_filter,
    detect_streamer_layout,
)

__all__ = [
    "OUT_W",
    "OUT_H",
    "detect_streamer_layout",
    "build_side_by_side_filter",
    "build_corner_40_60_filter",
    "build_fullscreen_9_16_filter",
    "build_deterministic_40_60_fallback",
]
