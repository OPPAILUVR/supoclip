"""Database CRUD & Complete Deletion/Toggle Lifecycle for Tracked Live Streamers."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .buffer_manager import (
    BUFFER_DIR,
    CLIPS_DIR,
    stop_buffer_recording,
    update_active_session_format,
)
from .cookies_and_probe import normalize_streamer_url, probe_live_status

logger = logging.getLogger(__name__)


async def record_event(
    db: AsyncSession,
    streamer_id: str,
    event_type: str,
    title: Optional[str] = None,
    virality_score: Optional[int] = None,
    task_id: Optional[str] = None,
    clip_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Log a live streaming event."""
    await db.execute(
        text("""
            INSERT INTO live_stream_events (
                id, streamer_id, task_id, clip_id, event_type, title, virality_score, details
            ) VALUES (
                uuid_generate_v4()::text, :streamer_id, :task_id, :clip_id, :event_type, :title, :score, :details
            )
        """),
        {
            "streamer_id": streamer_id,
            "task_id": task_id,
            "clip_id": clip_id,
            "event_type": event_type,
            "title": title,
            "score": virality_score,
            "details": json.dumps(details or {}),
        },
    )
    await db.commit()


async def add_streamer(
    db: AsyncSession,
    user_id: str,
    name: str,
    platform: str,
    identifier: str,
    buffer_minutes: int = 20,
    min_virality_score: int = 75,
    clip_format: str = "40_60",
) -> Dict[str, Any]:
    """Add a streamer to the watch list."""
    channel_url, handle = normalize_streamer_url(platform, identifier)
    streamer_id = str(uuid.uuid4())

    live_probe = await asyncio.to_thread(probe_live_status, platform, channel_url)
    is_live = live_probe.get("is_live", False)
    title = live_probe.get("title")
    stream_url = live_probe.get("stream_url")
    stream_id = live_probe.get("stream_id")

    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            INSERT INTO live_streamers (
                id, user_id, name, platform, channel_url, channel_handle,
                is_live, current_stream_title, current_stream_url, current_stream_id,
                last_checked_at, last_live_at, is_active, buffer_minutes, min_virality_score,
                clip_format
            ) VALUES (
                :id, :user_id, :name, :platform, :channel_url, :handle,
                :is_live, :title, :stream_url, :stream_id,
                :now, :last_live, true, :buffer_minutes, :min_virality_score,
                :clip_format
            )
        """),
        {
            "id": streamer_id,
            "user_id": user_id,
            "name": name,
            "platform": platform,
            "channel_url": channel_url,
            "handle": handle,
            "is_live": is_live,
            "title": title,
            "stream_url": stream_url,
            "stream_id": stream_id,
            "now": now,
            "last_live": now if is_live else None,
            "buffer_minutes": buffer_minutes,
            "min_virality_score": min_virality_score,
            "clip_format": clip_format,
        },
    )
    await db.commit()

    if is_live:
        await record_event(
            db, streamer_id, "stream_started", title=title, virality_score=None, details=live_probe
        )

    return {
        "id": streamer_id,
        "name": name,
        "platform": platform,
        "channel_url": channel_url,
        "channel_handle": handle,
        "is_live": is_live,
        "current_stream_title": title,
        "buffer_minutes": buffer_minutes,
        "min_virality_score": min_virality_score,
        "clip_format": clip_format,
        "is_active": True,
    }


async def list_streamers(db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
    """List tracked streamers and their latest stats for a user."""
    result = await db.execute(
        text("""
            SELECT s.*,
                   COUNT(e.id) FILTER (WHERE e.event_type = 'clip_generated') AS clip_count
            FROM live_streamers s
            LEFT JOIN live_stream_events e ON e.streamer_id = s.id
            WHERE s.user_id = :user_id
            GROUP BY s.id
            ORDER BY s.is_live DESC, s.created_at DESC
        """),
        {"user_id": user_id},
    )
    rows = result.fetchall()
    return [
        {
            "id": r.id,
            "name": r.name,
            "platform": r.platform,
            "channel_url": r.channel_url,
            "channel_handle": r.channel_handle,
            "is_live": r.is_live,
            "current_stream_title": r.current_stream_title,
            "current_task_id": r.current_task_id,
            "is_active": r.is_active,
            "buffer_minutes": r.buffer_minutes,
            "min_virality_score": r.min_virality_score,
            "clip_format": getattr(r, "clip_format", "40_60") or "40_60",
            "clip_count": r.clip_count,
            "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
            "last_live_at": r.last_live_at.isoformat() if r.last_live_at else None,
        }
        for r in rows
    ]


async def update_streamer_format(db: AsyncSession, user_id: str, streamer_id: str, clip_format: str) -> bool:
    """Update the clipping format preference ('40_60' vs 'crop') for a streamer."""
    res = await db.execute(
        text("""
            UPDATE live_streamers
            SET clip_format = :clip_format,
                updated_at = :now
            WHERE id = :id AND user_id = :user_id
        """),
        {
            "id": streamer_id,
            "user_id": user_id,
            "clip_format": clip_format,
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()
    update_active_session_format(streamer_id, clip_format)
    return res.rowcount > 0


async def delete_streamer(db: AsyncSession, user_id: str, streamer_id: str) -> bool:
    """Completely remove streamer, stop all active sessions, and wipe all clips, tasks, events, and files."""
    res = await db.execute(
        text("SELECT id, name, current_task_id FROM live_streamers WHERE id = :id AND user_id = :user_id"),
        {"id": streamer_id, "user_id": user_id},
    )
    streamer = res.fetchone()
    if not streamer:
        return False

    streamer_name = streamer[1]
    current_task_id = streamer[2]

    stop_buffer_recording(streamer_id)
    for bdir in (BUFFER_DIR / streamer_id, Path("uploads/live_buffers") / streamer_id):
        if bdir.exists():
            shutil.rmtree(bdir, ignore_errors=True)

    task_ids = set()
    if current_task_id:
        task_ids.add(str(current_task_id))

    task_res = await db.execute(
        text("""
            SELECT id FROM tasks
            WHERE user_id = :user_id
              AND (
                  CAST(source_metadata AS TEXT) ILIKE :meta_pattern
                  OR CAST(source_metadata AS TEXT) ILIKE :meta_pattern_loose
              )
        """),
        {
            "user_id": user_id,
            "meta_pattern": f'%"streamer": "{streamer_name}"%',
            "meta_pattern_loose": f"%{streamer_name}%",
        },
    )
    for tr in task_res.fetchall():
        task_ids.add(str(tr[0]))

    clip_paths = set()
    if task_ids:
        clips_res = await db.execute(
            text("SELECT id, file_path, filename FROM generated_clips WHERE task_id = ANY(:tids)"),
            {"tids": list(task_ids)},
        )
        for cr in clips_res.fetchall():
            if cr.file_path:
                clip_paths.add(Path(cr.file_path))

    streamer_clips_res = await db.execute(
        text("SELECT id, file_path, filename FROM generated_clips WHERE workflow_meta->>'streamer' = :streamer_name"),
        {"streamer_name": streamer_name},
    )
    for cr in streamer_clips_res.fetchall():
        if cr.file_path:
            clip_paths.add(Path(cr.file_path))

    for cdir in (CLIPS_DIR, Path("clips")):
        if cdir.exists():
            id_prefix = streamer_id[:8]
            for clip_file in cdir.glob(f"*{id_prefix}*"):
                clip_paths.add(clip_file)
            for clip_file in cdir.glob(f"*{streamer_name}*"):
                clip_paths.add(clip_file)

    for p in clip_paths:
        try:
            if p.exists():
                p.unlink(missing_ok=True)
            for ext in ["_thumb.jpg", "_thumb_16x9.jpg", ".ass", ".srt"]:
                companion = p.parent / f"{p.stem}{ext}"
                if companion.exists():
                    companion.unlink(missing_ok=True)
        except Exception as file_err:
            logger.warning("Error deleting clip file %s: %s", p, file_err)

    await db.execute(text("DELETE FROM live_stream_events WHERE streamer_id = :id"), {"id": streamer_id})
    if task_ids:
        await db.execute(text("DELETE FROM generated_clips WHERE task_id = ANY(:tids)"), {"tids": list(task_ids)})
    await db.execute(
        text("DELETE FROM generated_clips WHERE workflow_meta->>'streamer' = :streamer_name"),
        {"streamer_name": streamer_name},
    )
    if task_ids:
        await db.execute(text("DELETE FROM tasks WHERE id = ANY(:tids)"), {"tids": list(task_ids)})

    del_res = await db.execute(
        text("DELETE FROM live_streamers WHERE id = :id AND user_id = :user_id"),
        {"id": streamer_id, "user_id": user_id},
    )
    await db.commit()
    logger.info("Completely deleted streamer %s (%s) and all associated clips, tasks, and buffers.", streamer_name, streamer_id)
    return del_res.rowcount > 0


async def toggle_streamer(db: AsyncSession, user_id: str, streamer_id: str, is_active: bool) -> bool:
    """Toggle active monitoring for a streamer (Active vs Paused)."""
    if not is_active:
        stop_buffer_recording(streamer_id)
        for bdir in (BUFFER_DIR / streamer_id, Path("uploads/live_buffers") / streamer_id):
            if bdir.exists():
                shutil.rmtree(bdir, ignore_errors=True)
        res = await db.execute(
            text("""
                UPDATE live_streamers
                SET is_active = false, is_live = false, current_stream_url = null
                WHERE id = :id AND user_id = :user_id
            """),
            {"id": streamer_id, "user_id": user_id},
        )
    else:
        res = await db.execute(
            text("UPDATE live_streamers SET is_active = true WHERE id = :id AND user_id = :user_id"),
            {"id": streamer_id, "user_id": user_id},
        )
    await db.commit()
    return res.rowcount > 0


async def get_streamer_clips(db: AsyncSession, streamer_id: str) -> List[Dict[str, Any]]:
    """Return all clips generated for this streamer or all streamers."""
    if streamer_id == "all":
        result = await db.execute(
            text("""
                SELECT c.*, e.title as event_title, e.virality_score as event_virality,
                       s.name as streamer_name, s.platform as streamer_platform
                FROM live_stream_events e
                JOIN generated_clips c ON c.id = e.clip_id
                LEFT JOIN live_streamers s ON s.id = e.streamer_id
                WHERE e.event_type = 'clip_generated'
                ORDER BY c.created_at DESC
            """)
        )
    else:
        result = await db.execute(
            text("""
                SELECT c.*, e.title as event_title, e.virality_score as event_virality,
                       s.name as streamer_name, s.platform as streamer_platform
                FROM live_stream_events e
                JOIN generated_clips c ON c.id = e.clip_id
                LEFT JOIN live_streamers s ON s.id = e.streamer_id
                WHERE e.streamer_id = :streamer_id AND e.event_type = 'clip_generated'
                ORDER BY c.created_at DESC
            """),
            {"streamer_id": streamer_id},
        )
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "task_id": str(r.task_id),
            "title": r.hook_title or r.event_title or f"Live Clip {r.clip_order}",
            "filename": r.filename,
            "url": f"/api/tasks/{r.task_id}/clips/{r.id}/file",
            "virality_score": r.virality_score or r.event_virality or 0,
            "hook": r.reasoning or "",
            "duration": r.duration,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "streamer_name": getattr(r, "streamer_name", None),
            "streamer_platform": getattr(r, "streamer_platform", None),
        }
        for r in rows
    ]
