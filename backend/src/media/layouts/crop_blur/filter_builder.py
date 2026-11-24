"""FFmpeg filter-graph builders for Top-Down Blur ('crop') vertical layout (1080x1920)."""

from __future__ import annotations

from typing import Any, Dict


def build_crop_blur_layout() -> Dict[str, Any]:
    """Build the Top-Down Blur ambient-canvas 9:16 layout filter.

    Preserves 88% width (6% L/R crop) and 98% height (1% T/B crop) foreground
    centered over a blurred 1080x1920 ambient background canvas.
    """
    video_filter = (
        "[0:v]split=2[bgsrc][fgsrc];"
        "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
        "[fgsrc]crop=trunc(iw*0.88/2)*2:trunc(ih*0.98/2)*2:trunc(iw*0.06/2)*2:trunc(ih*0.01/2)*2,"
        "scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
    )
    return {
        "video_filter": video_filter,
        "mode": "complex",
        "caption_y": 0.80,
        "layout_type": "crop_top_down_blur",
    }
