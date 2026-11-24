#!/usr/bin/env python3
"""Backwards-compatible facade for High-CTR 9:16 Viral Thumbnail Generator.

Implementation is cleanly organized under:
  backend/src/services/thumbnail/
    - frame_selector.py  : Dual-frame peak face + peak action hotspot detector
    - visual_fx.py       : Dramatic image alterations, HDR grade, siren/fire FX, spyglass zoom
    - headline_engine.py : Bundled high-impact fonts, glyph-safe hooks, vector badges
    - generator.py       : High-CTR 9:16 & 16:9 thumbnail compositor
"""

from __future__ import annotations

import sys
from pathlib import Path

from .thumbnail import (
    CANDIDATE_FONTS,
    _get_best_font,
    _synthesize_thumbnail_headline,
    generate_viral_thumbnail,
)

__all__ = [
    "CANDIDATE_FONTS",
    "_get_best_font",
    "_synthesize_thumbnail_headline",
    "generate_viral_thumbnail",
]

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python thumbnail_generator.py <video_path> [hook_title]")
        sys.exit(1)

    vid = Path(sys.argv[1])
    hook = sys.argv[2] if len(sys.argv) > 2 else vid.stem
    out = generate_viral_thumbnail(vid, hook)
    print(f"Generated: {out}")
