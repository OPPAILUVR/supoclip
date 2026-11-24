"""Unified LiveStreamService facade delegating cleanly to modular live_clipper modules."""

from __future__ import annotations

from .buffer_manager import (
    ActiveLiveSession,
    clean_analysis_artifacts,
    cleanup_orphaned_buffers,
    cleanup_orphaned_buffers_async,
    get_active_session_ids,
    purge_old_segments,
    start_buffer_recording,
    stop_buffer_recording,
)
from .cookies_and_probe import (
    get_youtube_cookies_file,
    normalize_streamer_url,
    probe_live_status,
)
from .moment_evaluator import evaluate_buffer_for_moments
from .streamer_repository import (
    add_streamer,
    delete_streamer,
    get_streamer_clips,
    list_streamers,
    record_event,
    toggle_streamer,
    update_streamer_format,
)
from .subtitles_and_titles import (
    GENERIC_OR_REPETITIVE_TITLES,
    generate_procedural_fallback_title,
    is_repetitive_or_generic,
    normalize_title,
    sanitize_clip_hook_title,
)


class LiveStreamService:
    """Facade exposing live stream probing, DB CRUD, buffer capture, and moment clipping."""

    GENERIC_OR_REPETITIVE_TITLES = GENERIC_OR_REPETITIVE_TITLES

    normalize_streamer_url = staticmethod(normalize_streamer_url)
    get_youtube_cookies_file = staticmethod(get_youtube_cookies_file)
    probe_live_status = staticmethod(probe_live_status)

    add_streamer = staticmethod(add_streamer)
    list_streamers = staticmethod(list_streamers)
    update_streamer_format = staticmethod(update_streamer_format)
    delete_streamer = staticmethod(delete_streamer)
    toggle_streamer = staticmethod(toggle_streamer)
    record_event = staticmethod(record_event)
    get_streamer_clips = staticmethod(get_streamer_clips)

    get_active_session_ids = staticmethod(get_active_session_ids)
    start_buffer_recording = staticmethod(start_buffer_recording)
    stop_buffer_recording = staticmethod(stop_buffer_recording)
    clean_analysis_artifacts = staticmethod(clean_analysis_artifacts)
    purge_old_segments = staticmethod(purge_old_segments)
    cleanup_orphaned_buffers = staticmethod(cleanup_orphaned_buffers)
    cleanup_orphaned_buffers_async = staticmethod(cleanup_orphaned_buffers_async)

    _normalize_title = staticmethod(normalize_title)
    _is_repetitive_or_generic = staticmethod(is_repetitive_or_generic)
    _generate_procedural_fallback_title = staticmethod(generate_procedural_fallback_title)
    sanitize_clip_hook_title = staticmethod(sanitize_clip_hook_title)

    evaluate_buffer_for_moments = staticmethod(evaluate_buffer_for_moments)


__all__ = ["LiveStreamService", "ActiveLiveSession"]
