"""Backwards-compatible facade for Live Stream Monitoring and Auto-Clipping.

The 2,100-line monolith has been decomposed into single-responsibility modules under:
  backend/src/services/live_clipper/
"""

from .live_clipper import (
    ActiveLiveSession,
    LiveStreamService,
    apply_context_preroll_and_postroll,
    build_live_clip_ass,
    is_phrase_incomplete,
)

_build_live_clip_ass = build_live_clip_ass

__all__ = [
    "LiveStreamService",
    "ActiveLiveSession",
    "apply_context_preroll_and_postroll",
    "is_phrase_incomplete",
    "build_live_clip_ass",
    "_build_live_clip_ass",
]
