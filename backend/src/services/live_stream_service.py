"""Live stream monitoring and real-time auto-clipping service for YouTube, Twitch, and Kick."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..database import AsyncSessionLocal
from ..ai import AntigravityDirectModel

logger = logging.getLogger(__name__)

BUFFER_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "live_buffers"
CLIPS_DIR = Path(__file__).resolve().parent.parent.parent / "clips"
FFMPEG_BIN = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "ffmpeg"
FFPROBE_BIN = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "ffprobe"


def _ffmpeg_path() -> str:
    if FFMPEG_BIN.exists():
        return str(FFMPEG_BIN)
    return "ffmpeg"


def _ffprobe_path() -> str:
    if FFPROBE_BIN.exists():
        return str(FFPROBE_BIN)
    return "ffprobe"


@dataclass
class ActiveLiveSession:
    streamer_id: str
    streamer_name: str
    platform: str
    stream_url: str
    task_id: str
    buffer_dir: Path
    process: Optional[subprocess.Popen] = None
    is_running: bool = True
    last_analyzed_segment: int = 0
    analyzed_timestamps: set[str] = field(default_factory=set)


# Active background streaming sessions: streamer_id -> ActiveLiveSession
_active_sessions: Dict[str, ActiveLiveSession] = {}
_sessions_lock = threading.Lock()


class LiveStreamService:
    """Service to track streamers, detect live events, manage 10-minute buffers, and auto-clip."""

    @staticmethod
    def normalize_streamer_url(platform: str, identifier: str) -> tuple[str, str]:
        """Normalize user input to (channel_url, channel_handle)."""
        platform = platform.lower().strip()
        identifier = identifier.strip()

        if platform == "youtube":
            # Match @handle or youtube.com/@handle or full live link
            if "youtube.com" in identifier or "youtu.be" in identifier:
                handle_match = re.search(r"@([a-zA-Z0-9_.-]+)", identifier)
                handle = f"@{handle_match.group(1)}" if handle_match else identifier
                if "/live" in identifier:
                    url = identifier
                else:
                    url = f"https://www.youtube.com/{handle}/live"
            else:
                handle = identifier if identifier.startswith("@") else f"@{identifier}"
                url = f"https://www.youtube.com/{handle}/live"
            return url, handle

        elif platform == "twitch":
            clean = identifier.replace("https://", "").replace("http://", "").replace("www.twitch.tv/", "").replace("twitch.tv/", "").strip("/")
            handle = clean.split("/")[0]
            url = f"https://www.twitch.tv/{handle}"
            return url, handle

        elif platform == "kick":
            clean = identifier.replace("https://", "").replace("http://", "").replace("www.kick.com/", "").replace("kick.com/", "").strip("/")
            handle = clean.split("/")[0]
            url = f"https://kick.com/{handle}"
            return url, handle

        raise ValueError(f"Unsupported platform: {platform}. Supported: youtube, twitch, kick")

    @staticmethod
    def probe_live_status(platform: str, channel_url: str) -> Dict[str, Any]:
        """Probe if a streamer is currently live using yt-dlp."""
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "playlist_items": "1",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if not info:
                    return {"is_live": False}

                is_live = info.get("is_live") is True or info.get("live_status") == "is_live"
                if is_live:
                    # Direct HLS stream manifest URL
                    stream_url = info.get("url")
                    if not stream_url and "formats" in info:
                        # find m3u8 format
                        for f in reversed(info["formats"]):
                            if f.get("protocol", "").startswith("m3u8") or ".m3u8" in f.get("url", ""):
                                stream_url = f.get("url")
                                break
                    return {
                        "is_live": True,
                        "title": info.get("title") or "Live Stream",
                        "stream_id": str(info.get("id") or ""),
                        "stream_url": stream_url or channel_url,
                        "thumbnail": info.get("thumbnail"),
                    }
                return {"is_live": False}
        except Exception as exc:
            # yt-dlp raises exception when offline on Twitch/Kick
            err_str = str(exc).lower()
            if "not currently live" in err_str or "offline" in err_str or "no video" in err_str:
                return {"is_live": False}
            logger.debug("yt-dlp live probe failed for %s (%s): %s", channel_url, platform, exc)
            return {"is_live": False, "error": str(exc)}

    @staticmethod
    async def add_streamer(
        db: AsyncSession,
        user_id: str,
        name: str,
        platform: str,
        identifier: str,
        buffer_minutes: int = 10,
        min_virality_score: int = 75,
    ) -> Dict[str, Any]:
        """Add a streamer to the watch list."""
        channel_url, handle = LiveStreamService.normalize_streamer_url(platform, identifier)
        streamer_id = str(uuid.uuid4())

        # Probe initial status
        live_probe = await asyncio.to_thread(LiveStreamService.probe_live_status, platform, channel_url)
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
                    last_checked_at, last_live_at, is_active, buffer_minutes, min_virality_score
                ) VALUES (
                    :id, :user_id, :name, :platform, :channel_url, :handle,
                    :is_live, :title, :stream_url, :stream_id,
                    :now, :last_live, true, :buffer_minutes, :min_virality_score
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
            },
        )
        await db.commit()

        if is_live:
            await LiveStreamService.record_event(
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
            "is_active": True,
        }

    @staticmethod
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
        streamers = []
        for r in rows:
            streamers.append({
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
                "clip_count": r.clip_count,
                "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
                "last_live_at": r.last_live_at.isoformat() if r.last_live_at else None,
            })
        return streamers

    @staticmethod
    async def delete_streamer(db: AsyncSession, user_id: str, streamer_id: str) -> bool:
        """Remove streamer and stop active recording session."""
        LiveStreamService.stop_buffer_recording(streamer_id)
        res = await db.execute(
            text("DELETE FROM live_streamers WHERE id = :id AND user_id = :user_id"),
            {"id": streamer_id, "user_id": user_id},
        )
        await db.commit()
        return res.rowcount > 0

    @staticmethod
    async def toggle_streamer(db: AsyncSession, user_id: str, streamer_id: str, is_active: bool) -> bool:
        """Toggle active monitoring for a streamer."""
        if not is_active:
            LiveStreamService.stop_buffer_recording(streamer_id)
        res = await db.execute(
            text("UPDATE live_streamers SET is_active = :is_active WHERE id = :id AND user_id = :user_id"),
            {"id": streamer_id, "user_id": user_id, "is_active": is_active},
        )
        await db.commit()
        return res.rowcount > 0

    @staticmethod
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

    @staticmethod
    async def get_streamer_clips(db: AsyncSession, streamer_id: str) -> List[Dict[str, Any]]:
        """Return all clips generated for this streamer."""
        result = await db.execute(
            text("""
                SELECT c.*, e.title as event_title, e.virality_score as event_virality
                FROM live_stream_events e
                JOIN generated_clips c ON c.id = e.clip_id
                WHERE e.streamer_id = :streamer_id AND e.event_type = 'clip_generated'
                ORDER BY c.created_at DESC
            """),
            {"streamer_id": streamer_id},
        )
        rows = result.fetchall()
        clips = []
        for r in rows:
            clips.append({
                "id": r.id,
                "task_id": r.task_id,
                "title": r.hook_title or r.event_title or f"Live Clip {r.clip_order}",
                "filename": r.filename,
                "url": f"/clips/{r.filename}",
                "virality_score": r.virality_score or r.event_virality or 0,
                "hook": r.reasoning or "",
                "duration": r.duration,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return clips

    # -------------------------------------------------------------------------
    # Buffer Management & Recording
    # -------------------------------------------------------------------------

    @staticmethod
    def start_buffer_recording(
        streamer_id: str,
        streamer_name: str,
        platform: str,
        stream_url: str,
        task_id: str,
        buffer_minutes: int = 10,
    ) -> ActiveLiveSession:
        """Start rolling FFmpeg capture into 60s segments."""
        with _sessions_lock:
            if streamer_id in _active_sessions and _active_sessions[streamer_id].is_running:
                return _active_sessions[streamer_id]

            stream_buffer_dir = BUFFER_DIR / streamer_id
            stream_buffer_dir.mkdir(parents=True, exist_ok=True)

            # ffmpeg segment command writing 60-second chunks
            # -segment_wrap rotates or we purge files older than buffer_minutes
            segment_template = str(stream_buffer_dir / "chunk_%04d.mp4")
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

            logger.info("Starting live rolling buffer for streamer %s (%s)...", streamer_name, streamer_id)
            log_file = stream_buffer_dir / "ffmpeg_capture.log"
            out = open(log_file, "a")
            proc = subprocess.Popen(cmd, stdout=out, stderr=out)

            session = ActiveLiveSession(
                streamer_id=streamer_id,
                streamer_name=streamer_name,
                platform=platform,
                stream_url=stream_url,
                task_id=task_id,
                buffer_dir=stream_buffer_dir,
                process=proc,
                is_running=True,
            )
            _active_sessions[streamer_id] = session
            return session

    @staticmethod
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
                # Cleanup buffer directory
                if session.buffer_dir.exists():
                    shutil.rmtree(session.buffer_dir, ignore_errors=True)
                logger.info("Stopped live buffer recording for streamer %s", streamer_id)

    @staticmethod
    def purge_old_segments(buffer_dir: Path, max_segments: int = 10) -> List[Path]:
        """Maintain a rolling 10-minute window by keeping at most `max_segments` (60s each)."""
        chunks = sorted(buffer_dir.glob("chunk_*.mp4"))
        # Exclude the very latest chunk being written right now
        if len(chunks) > max_segments + 1:
            excess = chunks[: len(chunks) - (max_segments + 1)]
            for old_chunk in excess:
                try:
                    old_chunk.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug("Failed to purge old chunk %s: %s", old_chunk, e)
        # Return currently available completed chunks
        return sorted(buffer_dir.glob("chunk_*.mp4"))

    # -------------------------------------------------------------------------
    # Sliding AI Moment Detection & Instant Clipping
    # -------------------------------------------------------------------------

    @staticmethod
    async def evaluate_buffer_for_moments(
        db: AsyncSession,
        session: ActiveLiveSession,
        min_virality: int = 75,
    ) -> List[Dict[str, Any]]:
        """Transcribe latest buffer window, analyze with Gemini Flash, and cut viral moments instantly."""
        # Get completed chunks (excluding the currently active recording file)
        chunks = sorted(session.buffer_dir.glob("chunk_*.mp4"))
        if len(chunks) < 2:
            return []  # Need at least 1-2 completed minutes

        # Consider the latest 3-5 completed chunks
        eligible_chunks = chunks[-5:-1] if len(chunks) >= 5 else chunks[:-1]
        if not eligible_chunks:
            return []

        # Merge these eligible chunks into a temporary analysis segment
        analysis_dir = session.buffer_dir / "analysis"
        analysis_dir.mkdir(exist_ok=True)

        concat_list_file = analysis_dir / "concat_list.txt"
        with open(concat_list_file, "w") as f:
            for c in eligible_chunks:
                f.write(f"file '{c.resolve()}'\n")

        merged_video = analysis_dir / "recent_window.mp4"
        merged_audio = analysis_dir / "recent_window.wav"

        # Concat chunks without re-encoding
        subprocess.run(
            [_ffmpeg_path(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file), "-c", "copy", str(merged_video)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Extract 16kHz mono WAV for Whisper
        subprocess.run(
            [_ffmpeg_path(), "-y", "-i", str(merged_video), "-vn", "-ac", "1", "-ar", "16000", str(merged_audio)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Transcribe with Whisper
        import whisper
        model = whisper.load_model("base")
        whisper_result = await asyncio.to_thread(model.transcribe, str(merged_audio), language="en", fp16=False)

        segments = whisper_result.get("segments", [])
        if not segments:
            return []

        # Format transcript lines with timestamps MM:SS
        transcript_lines = []
        for s in segments:
            start_m, start_s = divmod(int(s["start"]), 60)
            end_m, end_s = divmod(int(s["end"]), 60)
            text_line = s.get("text", "").strip()
            if text_line:
                transcript_lines.append(f"[{start_m:02d}:{start_s:02d} - {end_m:02d}:{end_s:02d}] {text_line}")

        if not transcript_lines or len(transcript_lines) < 2:
            return []

        full_transcript = "\n".join(transcript_lines)

        # Prompt Antigravity Gemini Flash bridge
        prompt = f"""You are a live stream short-form clipper for streamer "{session.streamer_name}".
Analyze this 2-5 minute window from their ongoing live broadcast.
Search for standout moments suitable for a 20-60 second vertical TikTok / YouTube Short:
- High energy reaction, drama, rage, hype, clutch gaming play, funny joke, or memorable punchline.

Transcript:
{full_transcript}

Respond ONLY with a JSON array of objects (or empty [] if no moment exceeds 75 virality):
[
  {{
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "hook_title": "Short punchy title (max 7 words)",
    "hook": "Opening 3-second hook text",
    "virality_score": 88,
    "reason": "Why this will go viral"
  }}
]
"""
        agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")
        try:
            ai_resp = await asyncio.to_thread(agent.request, prompt)
            raw_text = ai_resp.content if hasattr(ai_resp, "content") else str(ai_resp)

            # Extract JSON block
            json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
            if not json_match:
                return []

            candidate_moments = json.loads(json_match.group(0))
        except Exception as e:
            logger.warning("AI moment detection failed for %s: %s", session.streamer_name, e)
            return []

        generated_clips = []
        for moment in candidate_moments:
            score = moment.get("virality_score", 0)
            if score < min_virality:
                continue

            start_str = moment.get("start_time", "00:00")
            end_str = moment.get("end_time", "00:30")
            moment_key = f"{start_str}_{end_str}"
            if moment_key in session.analyzed_timestamps:
                continue
            session.analyzed_timestamps.add(moment_key)

            # Convert MM:SS to seconds
            def _to_sec(t_str: str) -> float:
                p = [float(x) for x in t_str.split(":")]
                return p[0] * 60 + p[1] if len(p) == 2 else float(p[0])

            start_s = max(0.0, _to_sec(start_str))
            end_s = max(start_s + 5.0, _to_sec(end_str))
            duration = end_s - start_s

            clip_id = str(uuid.uuid4())
            clip_filename = f"live_{session.streamer_id[:8]}_{int(time.time())}_{clip_id[:8]}.mp4"
            clip_dest = CLIPS_DIR / clip_filename
            CLIPS_DIR.mkdir(parents=True, exist_ok=True)

            # Cut and render vertical 9:16 crop with FFmpeg
            render_cmd = [
                _ffmpeg_path(),
                "-y",
                "-ss", str(start_s),
                "-to", str(end_s),
                "-i", str(merged_video),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "128k",
                str(clip_dest),
            ]
            subprocess.run(render_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Insert clip into generated_clips table
            await db.execute(
                text("""
                    INSERT INTO generated_clips (
                        id, task_id, filename, file_path, start_time, end_time, duration,
                        virality_score, hook_score, hook_title, reasoning, text, clip_order
                    ) VALUES (
                        :id, :task_id, :filename, :path, :start_time, :end_time, :duration,
                        :score, :score, :hook_title, :reason, :text, 1
                    )
                """),
                {
                    "id": clip_id,
                    "task_id": session.task_id,
                    "filename": clip_filename,
                    "path": str(clip_dest),
                    "start_time": start_str,
                    "end_time": end_str,
                    "duration": duration,
                    "score": score,
                    "hook_title": moment.get("hook_title") or f"Highlight from {session.streamer_name}",
                    "reason": moment.get("reason") or "Standout live moment",
                    "text": moment.get("hook") or "",
                },
            )

            # Update task clips list
            await db.execute(
                text("""
                    UPDATE tasks
                    SET generated_clips_ids = array_append(COALESCE(generated_clips_ids, '{}'), :clip_id),
                        status = 'completed',
                        progress = 100
                    WHERE id = :task_id
                """),
                {"task_id": session.task_id, "clip_id": clip_id},
            )

            # Record event in audit log
            await LiveStreamService.record_event(
                db,
                streamer_id=session.streamer_id,
                event_type="clip_generated",
                title=moment.get("hook_title"),
                virality_score=score,
                task_id=session.task_id,
                clip_id=clip_id,
                details=moment,
            )

            logger.info("Successfully generated live clip: %s (Virality %s)", clip_filename, score)
            generated_clips.append({"clip_id": clip_id, "filename": clip_filename, **moment})

        return generated_clips
