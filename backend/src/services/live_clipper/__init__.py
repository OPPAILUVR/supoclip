"""Modular Live Stream Auto-Clipper Service Package.

Focused files by responsibility:
  - cookies_and_probe.py    : YouTube cookies sync & yt-dlp live status probing
  - streamer_repository.py  : DB CRUD, format toggle, active/pause toggle, full delete
  - buffer_manager.py       : FFmpeg rolling buffer capture & 48h disk/DB pruning
  - context_trimmer.py      : Sentence-boundary snapping & pre/post-roll trimming
  - subtitles_and_titles.py : Whisper cache, ASS animated captions, unique hook titles
  - moment_evaluator.py     : Gemini Flash virality evaluation, layout rendering, thumbnailing
  - service.py              : LiveStreamService facade
"""

from .buffer_manager import ActiveLiveSession
from .context_trimmer import apply_context_preroll_and_postroll, is_phrase_incomplete
from .service import LiveStreamService
from .subtitles_and_titles import build_live_clip_ass

__all__ = [
    "LiveStreamService",
    "ActiveLiveSession",
    "apply_context_preroll_and_postroll",
    "is_phrase_incomplete",
    "build_live_clip_ass",
]
