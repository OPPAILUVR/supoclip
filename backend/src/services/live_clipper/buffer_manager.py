"""Live stream FFmpeg rolling buffer capture, session registry, and 48h disk/DB cleanup."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text

from ...database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Note: 4 levels up from backend/src/services/live_clipper/*.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
BUFFER_DIR = BACKEND_DIR / "uploads" / "live_buffers"
CLIPS_DIR = BACKEND_DIR / "clips"
FFMPEG_BIN = BACKEND_DIR / ".venv" / "bin" / "ffmpeg"
FFPROBE_BIN = BACKEND_DIR / ".venv" / "bin" / "ffprobe"


def _ffmpeg_path() -> str:
    if FFMPEG_BIN.exists():
        return str(FFMPEG_BIN)
    return "ffmpeg"


def _ffprobe_path() -> str:
    if FFPROBE_BIN.exists():
        return str(FFPROBE_BIN)
    return "ffprobe"


def _is_valid_mp4(file_path: Path) -> bool:
    """Check if an MP4 file is valid and can be demuxed (has valid moov atom)."""
    try:
        res = subprocess.run(
            [_ffprobe_path(), "-v", "error", str(file_path)],
            capture_output=True,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


@dataclass
class ActiveLiveSession:
    streamer_id: str
    streamer_name: str
    platform: str
    stream_url: str
    task_id: str
    buffer_dir: Path
    audio_url: Optional[str] = None
    process: Optional[subprocess.Popen] = None
    is_running: bool = True
    last_analyzed_segment: int = 0
    analyzed_timestamps: set[str] = field(default_factory=set)
    last_clipped_time: float = 0.0
    clip_format: str = "40_60"


# Active background streaming sessions: streamer_id -> ActiveLiveSession
_active_sessions: Dict[str, ActiveLiveSession] = {}
_sessions_lock = threading.Lock()


def get_active_session_ids() -> List[str]:
    """Return list of currently active live stream session IDs in memory."""
    with _sessions_lock:
        return list(_active_sessions.keys())


def update_active_session_format(streamer_id: str, clip_format: str) -> None:
    """Update the in-memory clip format preference for an active session if running."""
    with _sessions_lock:
        if streamer_id in _active_sessions:
            _active_sessions[streamer_id].clip_format = clip_format
            logger.info("Updated active live session %s clip_format to %s", streamer_id, clip_format)


def start_buffer_recording(
    streamer_id: str,
    streamer_name: str,
    platform: str,
    stream_url: str,
    task_id: str,
    buffer_minutes: int = 20,
    audio_url: Optional[str] = None,
    clip_format: str = "40_60",
) -> ActiveLiveSession:
    """Start rolling FFmpeg capture into 60s segments."""
    is_youtube = (
        str(platform).lower() == "youtube"
        or "youtube.com" in stream_url.lower()
        or "youtu.be" in stream_url.lower()
        or "googlevideo.com" in stream_url.lower()
    )

    with _sessions_lock:
        existing = _active_sessions.get(streamer_id)
        if existing and existing.is_running and existing.process and existing.process.poll() is None:
            if audio_url and not existing.audio_url:
                logger.warning("Existing session for %s was video-only; restarting with dual-track audio!", streamer_name)
                try:
                    existing.process.kill()
                except Exception:
                    pass
            else:
                existing.task_id = task_id
                existing.clip_format = clip_format
                return existing

        if existing and existing.process:
            try:
                existing.process.kill()
            except Exception:
                pass

        stream_buffer_dir = BUFFER_DIR / streamer_id
        stream_buffer_dir.mkdir(parents=True, exist_ok=True)
        segment_template = str(stream_buffer_dir / "chunk_%04d.mp4")

        if audio_url:
            cmd = [
                _ffmpeg_path(),
                "-y",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", stream_url,
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", audio_url,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-f", "segment",
                "-segment_time", "60",
                "-reset_timestamps", "1",
                segment_template,
            ]
        else:
            if is_youtube:
                logger.info("Capturing combined YouTube container for %s (%s) [audio embedded]", streamer_name, streamer_id)
            cmd = [
                _ffmpeg_path(),
                "-y",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
                "-i", stream_url,
                "-c", "copy",
                "-f", "segment",
                "-segment_time", "60",
                "-reset_timestamps", "1",
                segment_template,
            ]

        logger.info(
            "Starting live rolling buffer for streamer %s (%s) on %s... [dual_track_audio=%s]",
            streamer_name, streamer_id, platform, bool(audio_url),
        )
        log_file = stream_buffer_dir / "ffmpeg_capture.log"
        out = open(log_file, "a")
        proc = subprocess.Popen(cmd, stdout=out, stderr=out)

        session = ActiveLiveSession(
            streamer_id=streamer_id,
            streamer_name=streamer_name,
            platform=platform,
            stream_url=stream_url,
            audio_url=audio_url,
            task_id=task_id,
            buffer_dir=stream_buffer_dir,
            process=proc,
            is_running=True,
            clip_format=clip_format,
        )
        _active_sessions[streamer_id] = session
        return session


def stop_buffer_recording(streamer_id: str) -> None:
    """Gracefully terminate buffer recording and purge temporary chunks."""
    with _sessions_lock:
        session = _active_sessions.pop(streamer_id, None)
        if session:
            session.is_running = False
            if session.process:
                try:
                    session.process.terminate()
                    session.process.wait(timeout=3)
                except Exception:
                    try:
                        session.process.kill()
                    except Exception:
                        pass
            if session.buffer_dir.exists():
                shutil.rmtree(session.buffer_dir, ignore_errors=True)
            logger.info("Stopped live buffer recording and deleted buffer directory for streamer %s", streamer_id)

    for disk_buffer in (BUFFER_DIR / streamer_id, Path("uploads/live_buffers") / streamer_id):
        if disk_buffer.exists():
            shutil.rmtree(disk_buffer, ignore_errors=True)


def clean_analysis_artifacts(analysis_dir: Path) -> None:
    """Removes temporary analysis video/audio/ass files to prevent storage buildup."""
    if not analysis_dir.exists():
        return
    for filename in ["recent_window.mp4", "recent_window.wav", "concat_list.txt"]:
        (analysis_dir / filename).unlink(missing_ok=True)
    for f in analysis_dir.glob("source_*.mp4"):
        f.unlink(missing_ok=True)
    for f in analysis_dir.glob("clip_*.ass"):
        f.unlink(missing_ok=True)


def purge_old_segments(buffer_dir: Path, max_segments: int = 10) -> List[Path]:
    """Maintain a rolling buffer window by keeping at most `max_segments` completed chunks."""
    chunks = sorted(buffer_dir.glob("chunk_*.mp4"))
    if len(chunks) > max_segments + 1:
        excess = chunks[: len(chunks) - (max_segments + 1)]
        for old_chunk in excess:
            try:
                old_chunk.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Failed to purge old chunk %s: %s", old_chunk, e)
    return sorted(buffer_dir.glob("chunk_*.mp4"))


def cleanup_orphaned_buffers(max_age_hours: int = 48) -> int:
    """Purge orphaned buffer directories and prune rendered clips/thumbnails older than 48 hours."""
    freed_bytes = 0

    with _sessions_lock:
        active_ids = {s_id for s_id, s in _active_sessions.items() if s.is_running}

    if BUFFER_DIR.exists():
        for item in BUFFER_DIR.iterdir():
            if item.is_dir() and item.name not in active_ids:
                try:
                    dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    shutil.rmtree(item, ignore_errors=True)
                    freed_bytes += dir_size
                    logger.info("Purged orphaned buffer directory: %s (freed %.1f MB)", item.name, dir_size / (1024 * 1024))
                except Exception as e:
                    logger.warning("Could not purge orphaned buffer %s: %s", item, e)

    try:
        max_age_seconds = max_age_hours * 3600
        cutoff_ts = time.time() - max_age_seconds
        deleted_count = 0

        if CLIPS_DIR.exists():
            for fpath in CLIPS_DIR.iterdir():
                if fpath.is_file() and not fpath.name.startswith("."):
                    try:
                        if fpath.stat().st_mtime < cutoff_ts:
                            file_size = fpath.stat().st_size
                            fpath.unlink(missing_ok=True)
                            freed_bytes += file_size
                            deleted_count += 1
                    except Exception as del_err:
                        logger.debug("Failed deleting expired clip %s: %s", fpath, del_err)

        public_dir = BACKEND_DIR.parent / "frontend" / "public"
        if public_dir.exists():
            for pat in ("asmon_*.mp4", "caseoh_*.mp4", "test_*.mp4"):
                for fpath in public_dir.glob(pat):
                    try:
                        if fpath.stat().st_mtime < cutoff_ts:
                            file_size = fpath.stat().st_size
                            fpath.unlink(missing_ok=True)
                            freed_bytes += file_size
                            deleted_count += 1
                    except Exception:
                        pass

        if deleted_count > 0:
            logger.info(
                "48-Hour Clip Retention: pruned %d expired clip files (freed %.2f MB).",
                deleted_count,
                freed_bytes / (1024 * 1024),
            )
    except Exception as e:
        logger.warning("Error in 48-hour clip pruning: %s", e)

    return freed_bytes


async def cleanup_orphaned_buffers_async(max_age_hours: int = 48) -> int:
    """Async pruner: Executes filesystem pruning in thread and prunes matching DB rows > 48h."""
    freed_bytes = await asyncio.to_thread(cleanup_orphaned_buffers, max_age_hours)

    try:
        async with AsyncSessionLocal() as db:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            await db.execute(text("DELETE FROM live_stream_events WHERE created_at < :cutoff"), {"cutoff": cutoff_dt})
            await db.execute(text("DELETE FROM clip_exports WHERE created_at < :cutoff"), {"cutoff": cutoff_dt})
            await db.execute(text("DELETE FROM social_posts WHERE created_at < :cutoff"), {"cutoff": cutoff_dt})
            await db.execute(text("DELETE FROM generated_clips WHERE created_at < :cutoff"), {"cutoff": cutoff_dt})
            await db.execute(text("DELETE FROM task_processing_checkpoints WHERE updated_at < :cutoff"), {"cutoff": cutoff_dt})
            await db.execute(
                text("DELETE FROM tasks WHERE created_at < :cutoff AND workflow = 'highlights'"),
                {"cutoff": cutoff_dt},
            )
            await db.commit()
    except Exception as db_err:
        logger.warning("Database 48h pruning notice: %s", db_err)

    return freed_bytes
