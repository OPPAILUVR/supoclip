"""Continuous background worker for live stream detection, buffer management, and auto-clipping.

Processes all monitored live streamers simultaneously in parallel:
- Concurrent live stream probing
- Simultaneous background FFmpeg rolling buffer recording
- Parallel Whisper speech-to-text transcription
- Concurrent Antigravity Gemini Flash moment analysis
- Parallel facecam + content vertical clip rendering
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ..database import AsyncSessionLocal
from ..services.live_stream_service import LiveStreamService

logger = logging.getLogger("live_stream_worker")

# Prevent running multiple overlapping analysis cycles on the same streamer
_processing_streamers: set[str] = set()
_processing_lock = asyncio.Lock()


async def process_single_streamer(s: Any) -> None:
    """Analyze and clip an individual streamer independently with its own DB session."""
    streamer_id = s.id
    streamer_name = getattr(s, "name", "unknown")

    # Guard against concurrent runs for the SAME streamer
    async with _processing_lock:
        if streamer_id in _processing_streamers:
            logger.debug("Streamer %s is already being analyzed in a previous cycle, skipping", streamer_name)
            return
        _processing_streamers.add(streamer_id)

    try:
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)

            # Probe live status asynchronously in a thread
            probe = await asyncio.to_thread(
                LiveStreamService.probe_live_status, s.platform, s.channel_url
            )
            currently_live = probe.get("is_live", False)
            stream_title = probe.get("title") or s.current_stream_title or "Live Stream"
            stream_url = probe.get("stream_url") or s.current_stream_url
            stream_id = probe.get("stream_id")

            if currently_live and not s.is_live:
                # Streamer JUST WENT LIVE!
                logger.info("Streamer %s (%s) is now LIVE: %s", streamer_name, s.platform, stream_title)

                # Create dedicated task in tasks table so clips appear on UI
                task_id = str(uuid.uuid4())
                await db.execute(
                    text("""
                        INSERT INTO tasks (
                            id, user_id, status, progress, progress_message,
                            source_metadata, workflow, processing_mode
                        ) VALUES (
                            :id, :user_id, 'processing', 50, 'Monitoring live stream...',
                            :meta, 'highlights', 'fast'
                        )
                    """),
                    {
                        "id": task_id,
                        "user_id": s.user_id,
                        "meta": f'{{"title": "{stream_title}", "live": true, "platform": "{s.platform}", "streamer": "{streamer_name}"}}',
                    },
                )

                # Update streamer status
                await db.execute(
                    text("""
                        UPDATE live_streamers
                        SET is_live = true,
                            current_stream_title = :title,
                            current_stream_url = :url,
                            current_stream_id = :sid,
                            current_task_id = :task_id,
                            last_checked_at = :now,
                            last_live_at = :now
                        WHERE id = :id
                    """),
                    {
                        "id": s.id,
                        "title": stream_title,
                        "url": stream_url,
                        "sid": stream_id,
                        "task_id": task_id,
                        "now": now,
                    },
                )
                await db.commit()

                # Start rolling buffer recorder
                session = LiveStreamService.start_buffer_recording(
                    streamer_id=s.id,
                    streamer_name=streamer_name,
                    platform=s.platform,
                    stream_url=stream_url,
                    task_id=task_id,
                    buffer_minutes=s.buffer_minutes,
                    audio_url=probe.get("audio_url"),
                    clip_format=getattr(s, "clip_format", "40_60") or "40_60",
                )

                await LiveStreamService.record_event(
                    db, s.id, "stream_started", title=stream_title, task_id=task_id, details=probe
                )

            elif currently_live and s.is_live:
                # Streamer is STILL LIVE -> Maintain buffer & evaluate moments!
                task_id = s.current_task_id
                if not task_id:
                    task_id = str(uuid.uuid4())
                    await db.execute(
                        text("""
                            INSERT INTO tasks (
                                id, user_id, status, progress, progress_message,
                                source_metadata, workflow, processing_mode
                            ) VALUES (
                                :id, :user_id, 'processing', 50, 'Monitoring live stream...',
                                :meta, 'highlights', 'fast'
                            )
                        """),
                        {
                            "id": task_id,
                            "user_id": s.user_id,
                            "meta": f'{{"title": "{stream_title}", "live": true, "platform": "{s.platform}", "streamer": "{streamer_name}"}}',
                        },
                    )
                    await db.execute(
                        text("UPDATE live_streamers SET current_task_id = :task_id WHERE id = :id"),
                        {"id": s.id, "task_id": task_id},
                    )

                await db.execute(
                    text("UPDATE live_streamers SET last_checked_at = :now WHERE id = :id"),
                    {"id": s.id, "now": now},
                )
                await db.commit()

                session = LiveStreamService.start_buffer_recording(
                    streamer_id=s.id,
                    streamer_name=streamer_name,
                    platform=s.platform,
                    stream_url=stream_url,
                    task_id=task_id,
                    buffer_minutes=s.buffer_minutes,
                    audio_url=probe.get("audio_url"),
                    clip_format=getattr(s, "clip_format", "40_60") or "40_60",
                )

                # Maintain full 20-minute rolling buffer (20 chunks, 60s each) for rich context and topic-shift detection
                LiveStreamService.purge_old_segments(session.buffer_dir, max_segments=max(s.buffer_minutes, 20))

                # Run sliding AI moment detection & rendering in parallel
                clips = await LiveStreamService.evaluate_buffer_for_moments(
                    db, session, min_virality=s.min_virality_score
                )
                if clips:
                    logger.info("Generated %d new clips for %s live stream!", len(clips), streamer_name)

            elif not currently_live and s.is_live:
                # Streamer just WENT OFFLINE
                logger.info("Streamer %s (%s) has ended their live stream", streamer_name, s.platform)
                LiveStreamService.stop_buffer_recording(s.id)

                await db.execute(
                    text("""
                        UPDATE live_streamers
                        SET is_live = false,
                            current_stream_url = null,
                            last_checked_at = :now
                        WHERE id = :id
                    """),
                    {"id": s.id, "now": now},
                )
                if s.current_task_id:
                    await db.execute(
                        text("UPDATE tasks SET status = 'completed', progress = 100, progress_message = 'Live stream ended' WHERE id = :tid"),
                        {"tid": s.current_task_id},
                    )
                await db.commit()

                await LiveStreamService.record_event(
                    db, s.id, "stream_ended", title=s.current_stream_title, task_id=s.current_task_id
                )

            else:
                # OFFLINE and was OFFLINE -> update last_checked_at
                await db.execute(
                    text("UPDATE live_streamers SET last_checked_at = :now WHERE id = :id"),
                    {"id": s.id, "now": now},
                )
                await db.commit()

    except Exception as e:
        logger.error("Error monitoring streamer %s: %s", streamer_name, e)
    finally:
        async with _processing_lock:
            _processing_streamers.discard(streamer_id)


async def halt_inactive_streamer_sessions() -> None:
    """Checks running sessions in this worker process and immediately terminates any that were paused or deleted."""
    running_ids = LiveStreamService.get_active_session_ids()
    if not running_ids:
        return
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(text("SELECT id FROM live_streamers WHERE is_active = true"))
            active_ids = {r[0] for r in res.fetchall()}
        for running_id in running_ids:
            if running_id not in active_ids:
                logger.info("Streamer %s is paused or deleted. Halting buffer recording immediately.", running_id)
                LiveStreamService.stop_buffer_recording(running_id)
    except Exception as e:
        logger.debug("Notice in halt_inactive_streamer_sessions: %s", e)


async def run_live_stream_monitor_cycle() -> None:
    """Run concurrent polling and processing across ALL active streamers simultaneously."""
    # 1. Immediately halt any sessions that were paused or deleted
    await halt_inactive_streamer_sessions()

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("SELECT * FROM live_streamers WHERE is_active = true")
        )
        streamers = res.fetchall()

    if not streamers:
        return

    # Automatically purge orphaned stream buffers and prune clips older than 48 hours
    try:
        await LiveStreamService.cleanup_orphaned_buffers_async(max_age_hours=48)
    except Exception as clean_err:
        logger.warning("Periodic 48h clip cleanup notice: %s", clean_err)

    logger.debug("Executing simultaneous live analysis across %d active streamers...", len(streamers))

    # Run every streamer concurrently using asyncio.gather
    results = await asyncio.gather(
        *(process_single_streamer(s) for s in streamers),
        return_exceptions=True
    )

    for s, res in zip(streamers, results):
        if isinstance(res, Exception):
            logger.error("Unhandled exception for streamer %s: %s", getattr(s, "name", "unknown"), res)


async def live_stream_monitor_loop(poll_interval_seconds: int = 35) -> None:
    """Continuous daemon loop for live streamer monitoring."""
    logger.info("Live stream monitoring daemon started (polling every %ds, fully parallel)...", poll_interval_seconds)
    while True:
        try:
            await run_live_stream_monitor_cycle()
        except Exception as e:
            logger.error("Error in live stream monitor cycle: %s", e)
        # Check every 2s for rapid reaction to user pause/delete actions
        for _ in range(max(1, poll_interval_seconds // 2)):
            await asyncio.sleep(2)
            await halt_inactive_streamer_sessions()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(live_stream_monitor_loop())
