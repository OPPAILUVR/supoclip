"""40/60 Split Vertical Layout package (Facecam Detection + Filter Builders)."""

from .detector import detect_streamer_layout
from .filter_builder import (
    OUT_H,
    OUT_W,
    build_corner_40_60_filter,
    build_deterministic_40_60_fallback,
    build_fullscreen_9_16_filter,
    build_side_by_side_filter,
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
