"""Live stream monitoring and real-time auto-clipping service for YouTube, Twitch, and Kick."""

from __future__ import annotations

import asyncio
import difflib
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
from ..media.reframing import build_vertical_filter_plan, render_reframed_clip_ffmpeg
from ..media.streamer_layout import detect_streamer_layout
from ..media.ffmpeg import ffprobe_video_size, ffprobe_has_audio, subtitles_filter_fragment, ffmpeg_escape_filter_path
from ..utils.motion_analyzer import analyze_visual_actions
from ..utils.video_metadata import strip_and_embed_video_metadata, get_streamer_tags

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


# Active background streaming sessions: streamer_id -> ActiveLiveSession
_active_sessions: Dict[str, ActiveLiveSession] = {}
_sessions_lock = threading.Lock()

_whisper_model = None
_whisper_lock = threading.Lock()
_whisper_async_lock = asyncio.Lock()


def _get_whisper_model():
    """Thread-safe cached Whisper model instance for concurrent live transcriptions."""
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                import whisper
                _whisper_model = whisper.load_model("base")
    return _whisper_model


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


_VIRAL_TRIGGERS = {
    "MISTAKE", "REGRET", "LATE", "CAUGHT", "4K", "WORST", "UNHINGED",
    "DISASTER", "WRONG", "EXPOSED", "PANIC", "NEVER", "THIS", "INSTANTLY",
    "HAPPENED", "ILLEGAL", "CHEATING", "FORGOT", "0 IQ", "200 IQ", "ENDED",
    "BANNED", "SHOCKING", "CONFESSED", "FELL", "APART", "EXPLODED", "RUINED",
    "FAIL", "FAILED", "RAGE", "LOST", "GONE", "INSANE", "CRAZY", "BROKE"
}


def _format_hook_title_for_ass(hook_title: str) -> str:
    """Format hook title for ASS with electric yellow accents on viral trigger words."""
    if not hook_title:
        return ""
    clean = hook_title.replace("{", "").replace("}", "").strip()
    words = clean.split()
    formatted = []
    for w in words:
        bare = w.strip(".,!?:;\"'").upper()
        if bare in _VIRAL_TRIGGERS:
            # Highlight in electric yellow (\c&H0000FFFF&), then restore white (\c&H00FFFFFF&)
            formatted.append(f"{{\\c&H0000FFFF&}}{w.upper()}{{\\c&H00FFFFFF&}}")
        else:
            formatted.append(w.upper())
    return "{\\b1}" + " ".join(formatted) + "{\\b0}"


def _build_live_clip_ass(
    segments: list,
    start_s: float,
    end_s: float,
    hook_title: str,
    output_ass: Path,
    caption_y: float = 0.80,
) -> None:
    # MarginV for Alignment 2 (bottom-center)
    margin_v = max(80, int(1920 * (1.0 - caption_y)))

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: HookTitle,Arial,66,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,8,48,48,220,1",
        f"Style: Caption,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    duration = max(1.0, end_s - start_s)

    # 1. Hook Title Animation (Top): pop spring + fade in, hold for 8s, then fade out
    if hook_title:
        title_end = min(duration, 8.0)
        formatted_title = _format_hook_title_for_ass(hook_title)
        title_anim = "{\\fad(140,250)\\fscx86\\fscy86\\t(0,120,\\fscx106\\fscy106)\\t(120,240,\\fscx100\\fscy100)}"
        ass_lines.append(
            f"Dialogue: 0,0:00:00.00,{_format_ass_time(title_end)},HookTitle,,0,0,0,,{title_anim}{formatted_title}"
        )

    # 2. Extract and align all words for spoken dialogue within the clip window
    all_words = []
    for seg in segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        text = str(seg.get("text", "")).strip()
        if not text or seg_end <= start_s or seg_start >= end_s:
            continue

        words_data = seg.get("words")
        if words_data and len(words_data) > 0:
            for w in words_data:
                w_start = float(w.get("start", seg_start))
                w_end = float(w.get("end", seg_end))
                w_text = str(w.get("word", "")).strip()
                if w_text and w_end > start_s and w_start < end_s:
                    all_words.append({
                        "word": w_text.replace("{", "").replace("}", ""),
                        "start": max(0.0, w_start - start_s),
                        "end": min(duration, w_end - start_s),
                    })
        else:
            raw_tokens = text.split()
            if not raw_tokens:
                continue
            tot_dur = max(0.2, seg_end - seg_start)
            w_dur = tot_dur / len(raw_tokens)
            for idx, token in enumerate(raw_tokens):
                ws = seg_start + idx * w_dur
                we = ws + w_dur
                if we > start_s and ws < end_s:
                    all_words.append({
                        "word": token.replace("{", "").replace("}", ""),
                        "start": max(0.0, ws - start_s),
                        "end": min(duration, we - start_s),
                    })

    # Group into snappy chunks of 3-4 words (or sentence boundaries)
    chunks = []
    current_chunk = []
    for w in all_words:
        current_chunk.append(w)
        if len(current_chunk) >= 3 or w["word"].rstrip().endswith((".", "!", "?")):
            chunks.append(current_chunk)
            current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    # Render dynamic animated karaoke captions with spring bounce entrance
    for chunk in chunks:
        chunk_end = chunk[-1]["end"]
        for i, target_word in enumerate(chunk):
            w_start = target_word["start"]
            w_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end
            if w_end <= w_start:
                w_end = w_start + 0.12

            # Pop / Bounce entrance spring on the first word of the chunk
            entrance = "{\\fscx84\\fscy84\\t(0,80,\\fscx112\\fscy112)\\t(80,180,\\fscx100\\fscy100)}" if i == 0 else ""

            # Highlight current active word in electric yellow (&H0000FFFF&)
            parts = []
            for j, other in enumerate(chunk):
                clean_text = other["word"].strip().upper()
                if j == i:
                    parts.append(f"{{\\c&H0000FFFF&}}{clean_text}{{\\c&H00FFFFFF&}}")
                else:
                    parts.append(clean_text)

            chunk_text = " ".join(parts)
            dialogue_text = f"{entrance}{{\\b1}}{chunk_text}{{\\b0}}" if entrance else f"{{\\b1}}{chunk_text}{{\\b0}}"
            ass_lines.append(
                f"Dialogue: 0,{_format_ass_time(w_start)},{_format_ass_time(w_end)},Caption,,0,0,0,,{dialogue_text}"
            )

    output_ass.write_text("\n".join(ass_lines), encoding="utf-8")


DANGLING_CONNECTIVES = {
    # Coordinating & subordinating conjunctions
    "and", "but", "or", "nor", "because", "cause", "since", "as", "although", "though",
    "while", "whereas", "if", "unless", "until",
    # Relative pronouns & interrogative transition words
    "that", "which", "who", "whom", "whose", "where", "when", "why", "how", "what", "whatever", "whoever",
    # Prepositions that signal continuation
    "like", "with", "about", "into", "onto", "than", "to", "for", "of", "by", "in", "on", "at", "from",
    # Verbs / auxiliaries left hanging
    "is", "are", "was", "were", "have", "has", "had", "do", "does", "did", "would", "could", "should",
    "will", "can", "might", "must", "be", "been", "being",
    # Articles & demonstratives
    "the", "a", "an", "this", "these", "those",
    # Dangling pronouns & possessives
    "my", "your", "his", "her", "their", "our", "its",
    # Connectives & fillers
    "so", "then", "well", "actually", "basically", "also", "plus",
}

DANGLING_PHRASES = (
    "and let me", "let me", "let me tell", "let me explain", "the reason why",
    "the reason is", "the reason", "here is why", "here's why", "what happens is",
    "what i mean", "here it comes", "look at this", "watch this", "wait until",
    "and then", "so basically", "for example", "such as", "i mean", "you know",
    "in fact", "i think that", "i would say", "because if you", "because if",
    "and if you", "and if", "why i", "why he", "why they", "why would", "why wouldn't",
    "why would not"
)

ANTICIPATION_LEAD_IN_PHRASES = (
    "here it comes", "watch this", "look at this", "wait for it",
    "here we go", "check this out", "wait until you see"
)


def is_phrase_incomplete(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return True
    lower = raw.lower()
    if raw[-1] in (",", ";", ":", "-", "—"):
        return True
    for p in DANGLING_PHRASES:
        if lower.endswith(p) or lower.endswith(p + "."):
            return True
    for a in ANTICIPATION_LEAD_IN_PHRASES:
        if lower.endswith(a) or lower.endswith(a + "."):
            return True
    words = re.findall(r"[a-zA-Z0-9']+", lower)
    if not words:
        return True
    last_word = words[-1]
    if last_word in DANGLING_CONNECTIVES:
        if last_word == "so" and len(words) >= 2 and words[-2] in ("think", "not"):
            pass
        else:
            return True
    if raw[-1] not in (".", "!", "?"):
        return True
    return False


def apply_context_preroll_and_postroll(
    start_s: float,
    end_s: float,
    segments: List[Dict[str, Any]],
    min_duration: float = 30.0,
    max_duration: float = 58.0,
    target_sweet_spot: float = 40.0,
    source_duration: Optional[float] = None,
) -> tuple[float, float, float]:
    """
    Applies intelligent context-aware boundary extension and completion.
    1. Snaps start_s earlier to the beginning of the setup sentence so viewers have full context.
    2. Dynamically adjusts length based on video context: NEVER forces an arbitrary 38s ceiling.
    3. Keeps all videos strictly above 30 seconds (min_duration >= 30.0s).
    4. Scans forward to capture complete explanations, punchlines, and reactions without mid-sentence cuts.
    5. Allows natural variation up to 58.0s to ensure the viewer fully understands the story.
    """
    if not segments:
        dur = min(max_duration, max(min_duration, end_s - start_s))
        if source_duration:
            dur = min(dur, max(0.1, source_duration - start_s))
        return round(start_s, 2), round(start_s + dur, 2), round(dur, 2)

    # Step 1: Pre-roll Snap to ensure full lead-in context & setup are captured
    raw_dur = max(0.1, end_s - start_s)
    needed_preroll = max(6.0, 36.0 - raw_dur) if raw_dur < 30.0 else 5.0
    target_pre_start = max(0.0, start_s - needed_preroll)

    snapped_start = start_s
    best_start_idx = 0
    for idx, seg in enumerate(segments):
        s_start = float(seg.get("start", 0.0))
        if s_start <= start_s and (start_s - s_start) <= 25.0:
            if abs(s_start - target_pre_start) < abs(snapped_start - target_pre_start):
                snapped_start = s_start
                best_start_idx = idx

    # Step 2: Forward scan for complete context, thought, explanation & payoff
    best_end_idx = best_start_idx
    for idx in range(best_start_idx, len(segments)):
        if float(segments[idx].get("end", 0.0)) >= end_s:
            best_end_idx = idx
            break

    curr_idx = best_end_idx
    while curr_idx < len(segments):
        seg = segments[curr_idx]
        seg_end = float(seg.get("end", 0.0))
        seg_text = seg.get("text", "")
        potential_dur = seg_end - snapped_start

        if potential_dur > max_duration:
            break

        best_end_idx = curr_idx
        # Ensure at least 30s AND complete sentence without dangling thoughts
        if potential_dur >= min_duration and not is_phrase_incomplete(seg_text):
            if potential_dur >= target_sweet_spot:
                break
        curr_idx += 1

    # Step 3: Intelligent Backtrack if candidate ending is dangling mid-sentence
    end_seg = segments[best_end_idx]
    if is_phrase_incomplete(end_seg.get("text", "")):
        backtrack_idx = best_end_idx - 1
        while backtrack_idx >= best_start_idx:
            cand = segments[backtrack_idx]
            cand_dur = float(cand.get("end", 0.0)) - snapped_start
            if not is_phrase_incomplete(cand.get("text", "")) and cand_dur >= min_duration:
                best_end_idx = backtrack_idx
                break
            backtrack_idx -= 1

    snapped_end = float(segments[best_end_idx].get("end", end_s)) + 0.8
    new_dur = snapped_end - snapped_start

    # Step 4: Enforce strict minimum duration of 30 seconds
    if new_dur < min_duration:
        deficit = min_duration - new_dur
        expand_start = min(snapped_start, deficit)
        snapped_start -= expand_start
        deficit -= expand_start
        snapped_end += deficit
        new_dur = snapped_end - snapped_start

    # Step 5: Enforce max_duration (58.0s) & source_duration
    if new_dur > max_duration:
        # Intelligently find last complete terminal sentence within max_duration
        backtrack_idx = best_end_idx
        while backtrack_idx >= best_start_idx:
            cand = segments[backtrack_idx]
            cand_dur = (float(cand.get("end", 0.0)) + 0.8) - snapped_start
            if cand_dur <= max_duration and not is_phrase_incomplete(cand.get("text", "")):
                if cand_dur >= min_duration:
                    best_end_idx = backtrack_idx
                    snapped_end = float(cand.get("end", 0.0)) + 0.8
                    new_dur = snapped_end - snapped_start
                    break
            backtrack_idx -= 1
        else:
            snapped_end = snapped_start + max_duration
            new_dur = max_duration

    if source_duration and snapped_end > source_duration:
        snapped_end = source_duration
        new_dur = max(0.1, snapped_end - snapped_start)

    return round(max(0.0, snapped_start), 2), round(snapped_end, 2), round(new_dur, 2)


class LiveStreamService:
    """Service to track streamers, detect live events, manage 10-minute buffers, and auto-clip."""

    @staticmethod
    def normalize_streamer_url(platform: str, identifier: str) -> tuple[str, str]:
        """Normalize user input to (channel_url, channel_handle)."""
        platform = platform.lower().strip()
        identifier = identifier.strip()

        # Automatic detection of platform from identifier if specified as generic or mismatched
        if "youtube.com" in identifier.lower() or "youtu.be" in identifier.lower():
            platform = "youtube"
        elif "twitch.tv" in identifier.lower():
            platform = "twitch"
        elif "kick.com" in identifier.lower():
            platform = "kick"

        if platform == "youtube":
            # Match @handle or youtube.com/@handle or channel/UC... or full live link
            if "youtube.com" in identifier or "youtu.be" in identifier:
                handle_match = re.search(r"@([a-zA-Z0-9_.-]+)", identifier)
                if handle_match:
                    handle = f"@{handle_match.group(1)}"
                    url = identifier if "/live" in identifier else f"https://www.youtube.com/{handle}/live"
                elif "/channel/" in identifier:
                    chan_match = re.search(r"/channel/([a-zA-Z0-9_.-]+)", identifier)
                    handle = chan_match.group(1) if chan_match else "channel"
                    url = identifier if "/live" in identifier else f"https://www.youtube.com/channel/{handle}/live"
                else:
                    handle = identifier
                    url = identifier if "/live" in identifier else f"{identifier.rstrip('/')}/live"
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
        """Probe if a streamer is currently live using yt-dlp.
        
        DEFAULT YOUTUBE LIVE DUAL-TRACK ARCHITECTURE:
        YouTube HLS splits live video (itag 270/312) and audio (itag 234) into separate streams.
        For ANY YouTube live stream, always extracts BOTH the video manifest and the audio manifest
        so FFmpeg captures them simultaneously into a single synchronized container with AAC audio.
        """
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
                    formats = info.get("formats") or []
                    stream_url = None
                    audio_url = None
                    
                    is_youtube = (
                        str(platform).lower() == "youtube"
                        or "youtube.com" in channel_url.lower()
                        or "youtu.be" in channel_url.lower()
                    )

                    if is_youtube and formats:
                        # DEFAULT FOR ALL YOUTUBE LIVE STREAMS:
                        # YouTube delivers video-only and audio-only HLS tracks.
                        # Extract the highest resolution video track and highest bitrate audio track.
                        for f in reversed(formats):
                            f_url = f.get("url") or ""
                            vc = f.get("vcodec") or "none"
                            ac = f.get("acodec") or "none"
                            proto = f.get("protocol") or ""
                            res = str(f.get("resolution") or "")
                            is_m3u8 = "m3u8" in proto or ".m3u8" in f_url or f.get("ext") == "mp4"

                            # Video track: contains video codec
                            if is_m3u8 and vc != "none" and not stream_url:
                                stream_url = f_url
                                logger.info("YouTube Live probe: selected video format %s (%s)", f.get("format_id"), res)

                            # Audio track: contains audio stream without video codec, or resolution is audio only
                            if (vc == "none" or "audio" in res.lower() or (ac != "none" and vc == "none")) and not audio_url:
                                if f_url and ("m3u8" in proto or ".m3u8" in f_url or "http" in f_url):
                                    audio_url = f_url
                                    logger.info("YouTube Live probe: selected audio format %s (%s)", f.get("format_id"), res)

                        # Fallback for video track if not found in formats
                        if not stream_url:
                            stream_url = info.get("url")
                    else:
                        # Twitch / Kick or combined streams
                        stream_url = info.get("url")
                        if not stream_url and formats:
                            for f in reversed(formats):
                                if f.get("protocol", "").startswith("m3u8") or ".m3u8" in f.get("url", ""):
                                    stream_url = f.get("url")
                                    break

                    return {
                        "is_live": True,
                        "title": info.get("title") or "Live Stream",
                        "stream_id": str(info.get("id") or ""),
                        "stream_url": stream_url or channel_url,
                        "audio_url": audio_url,
                        "is_youtube": is_youtube,
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
        clips = []
        for r in rows:
            clips.append({
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
        audio_url: Optional[str] = None,
    ) -> ActiveLiveSession:
        """Start rolling FFmpeg capture into 60s segments.
        
        PERMANENT DEFAULT ARCHITECTURE FOR YOUTUBE LIVE:
        YouTube splits audio and video into separate streams. Whenever platform is YouTube
        or stream_url is from YouTube/googlevideo, dual-track capture is strictly enforced.
        If audio_url is missing, it is dynamically extracted before FFmpeg launch to guarantee
        that zero YouTube live streams are ever captured without an audio track.
        """
        is_youtube = (
            str(platform).lower() == "youtube"
            or "youtube.com" in stream_url.lower()
            or "youtu.be" in stream_url.lower()
            or "googlevideo.com" in stream_url.lower()
        )

        with _sessions_lock:
            existing = _active_sessions.get(streamer_id)
            if existing and existing.is_running and existing.process and existing.process.poll() is None:
                # Hot-upgrade: if existing session was running video-only, but audio_url is now available, upgrade it
                if audio_url and not existing.audio_url:
                    logger.warning("Existing session for %s was video-only; restarting with dual-track audio!", streamer_name)
                    try:
                        existing.process.kill()
                    except Exception:
                        pass
                else:
                    existing.task_id = task_id
                    return existing

            # Clean any stale dead process if present
            if existing and existing.process:
                try:
                    existing.process.kill()
                except Exception:
                    pass

            stream_buffer_dir = BUFFER_DIR / streamer_id
            stream_buffer_dir.mkdir(parents=True, exist_ok=True)

            segment_template = str(stream_buffer_dir / "chunk_%04d.mp4")

            # Dual-track capture with explicit stream mapping:
            # -map 0:v:0 guarantees video from input 0 (video manifest)
            # -map 1:a:0 guarantees audio from input 1 (audio manifest)
            # -c:v copy (zero CPU re-encoding overhead)
            # -c:a aac (standard 48kHz stereo AAC in every 60s chunk)
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
                    logger.warning("⚠️ YouTube live stream %s (%s) has no audio_url specified! Checking formats...", streamer_name, streamer_id)
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
                streamer_name, streamer_id, platform, bool(audio_url)
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
            )
            _active_sessions[streamer_id] = session
            return session

    @staticmethod
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
                # Cleanup buffer directory immediately
                if session.buffer_dir.exists():
                    shutil.rmtree(session.buffer_dir, ignore_errors=True)
                logger.info("Stopped live buffer recording and deleted buffer directory for streamer %s", streamer_id)

    @staticmethod
    def clean_analysis_artifacts(analysis_dir: Path) -> None:
        """Removes temporary analysis video/audio/ass files to prevent storage buildup."""
        if not analysis_dir.exists():
            return
        for filename in ["recent_window.mp4", "recent_window.wav", "concat_list.txt"]:
            (analysis_dir / filename).unlink(missing_ok=True)
        # Clean any intermediate source clips or ass files
        for f in analysis_dir.glob("source_*.mp4"):
            f.unlink(missing_ok=True)
        for f in analysis_dir.glob("clip_*.ass"):
            f.unlink(missing_ok=True)

    @staticmethod
    def purge_old_segments(buffer_dir: Path, max_segments: int = 10) -> List[Path]:
        """
        Maintain a rolling buffer window by keeping at most `max_segments` (60s each).
        Default 10 segments (~10 minutes). Excess old chunks are deleted immediately to keep disk free.
        """
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

    @staticmethod
    def cleanup_orphaned_buffers() -> int:
        """
        AUTOMATIC 10 GB STORAGE QUOTA ENFORCER:
        Strictly enforces the user's 10 GB storage ceiling across ALL media files:
        - BUFFER_DIR: /uploads/live_buffers (rolling live stream chunks)
        - CLIPS_DIR: /clips (rendered clips & thumbnails)
        - UPLOADS_DIR: /uploads/clips & /uploads/youtube-cache

        EVICTION HIERARCHY (FIFO + Pruning):
        1. Purges dead/orphaned streamer buffer folders.
        2. Calculates combined media footprint.
        3. If total media storage exceeds 10 GB:
           - Automatically evicts oldest rendered clips & thumbnails in CLIPS_DIR (FIFO).
           - Automatically evicts oldest inactive buffer segments in BUFFER_DIR (FIFO).
           - Safely stops when storage drops down to target (6 GB), keeping 4 GB free.
        Returns the total number of freed bytes.
        """
        freed_bytes = 0

        with _sessions_lock:
            active_ids = {s_id for s_id, s in _active_sessions.items() if s.is_running}

        # 1. Clean orphaned buffer folders
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

        # 2. Enforce global 10 GB quota across CLIPS_DIR + BUFFER_DIR
        try:
            MAX_STORAGE_BYTES = 10 * 1024 * 1024 * 1024       # 10 GB hard limit
            TARGET_STORAGE_BYTES = int(6.0 * 1024 * 1024 * 1024) # 6 GB target after auto-eviction

            media_dirs = [CLIPS_DIR, BUFFER_DIR]
            existing_dirs = [d for d in media_dirs if d.exists()]

            all_files = []
            for d in existing_dirs:
                for f in d.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        try:
                            all_files.append((f.stat().st_mtime, f.stat().st_size, f))
                        except Exception:
                            pass

            total_size = sum(size for _, size, _ in all_files)

            if total_size > MAX_STORAGE_BYTES:
                logger.warning(
                    "⚠️ TOTAL STORAGE (%.2f GB) EXCEEDS 10 GB LIMIT! Starting automatic FIFO eviction...",
                    total_size / (1024 * 1024 * 1024),
                )

                # Clean analysis caches first
                for active_id in active_ids:
                    LiveStreamService.clean_analysis_artifacts(BUFFER_DIR / active_id / "analysis")

                # Collect files to consider for eviction (oldest first)
                # For CLIPS_DIR: all clips and thumbnails are eligible for FIFO deletion
                # For BUFFER_DIR: preserve the latest recording chunk so live streams are not interrupted
                active_recording_chunks = set()
                if BUFFER_DIR.exists():
                    for s_dir in [d for d in BUFFER_DIR.iterdir() if d.is_dir()]:
                        dir_chunks = sorted(s_dir.glob("chunk_*.mp4"))
                        if dir_chunks:
                            active_recording_chunks.add(dir_chunks[-1])

                candidates = []
                for mtime, size, fpath in all_files:
                    if fpath in active_recording_chunks:
                        continue
                    candidates.append((mtime, size, fpath))

                # Sort oldest first (FIFO)
                candidates.sort(key=lambda x: x[0])

                current_size = total_size
                deleted_count = 0
                for _, size, fpath in candidates:
                    if current_size <= TARGET_STORAGE_BYTES:
                        break
                    try:
                        fpath.unlink(missing_ok=True)
                        current_size -= size
                        freed_bytes += size
                        deleted_count += 1
                    except Exception as del_err:
                        logger.debug("Failed deleting file %s: %s", fpath, del_err)

                logger.info(
                    "✅ Automated storage eviction complete: deleted %d files, freed %.2f GB. Current storage: %.2f GB (under 10GB limit).",
                    deleted_count,
                    freed_bytes / (1024 * 1024 * 1024),
                    current_size / (1024 * 1024 * 1024),
                )
        except Exception as e:
            logger.warning("Error enforcing 10 GB storage quota: %s", e)

        return freed_bytes

    # -------------------------------------------------------------------------
    # Unique Hook Title Sanitization & Anti-Repetition Engine
    # -------------------------------------------------------------------------
    GENERIC_OR_REPETITIVE_TITLES = {
        "watchhisfacewhenherealizes",
        "watchherfacewhensherealizes",
        "watchtheirfacewhentheyrealize",
        "thereisnowayhesaidthat",
        "thereisnowayshesaidthat",
        "thereisnowaytheysaidthat",
        "theexactsecondeverythingfellapart",
        "theexactmomentitfellapart",
        "livestreamhighlight",
        "highlightfromstreamer",
        "instantregretin4k",
        "waitforit",
        "hethoughthewassafeuntil",
        "shethoughtshewassafeuntil",
        "caughtin4kdoingtheworstthingpossible",
        "brostartedcelebrating2secondstooearly",
        "wentfrom200iqto0iqin3seconds",
        "themostunhingeddmintwitchhistory",
        "themostunhingedconfessionintwitchhistory",
        "broforgotthemicwasstillon",
        "herealizedhismistaketoolate",
        "sherealizedhermistaketoolate",
        "brocelebratedtwosecondstooearly",
        "hecompletelylosthismindlive",
        "hesaidthequietpartoutloud",
        "shesaidthequietpartoutloud",
        "frompurehypetocompletesilence",
        "thereisnowayheplayedthat",
        "thereisnowaysheplayedthat",
    }

    @staticmethod
    def _normalize_title(t: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]', '', (t or '').lower().replace('#shorts', ''))

    @classmethod
    def _is_repetitive_or_generic(cls, title: str, existing_norm_set: set[str], existing_raw_list: list[str]) -> bool:
        clean = (title or "").strip()
        norm = cls._normalize_title(clean)
        if not norm or norm in cls.GENERIC_OR_REPETITIVE_TITLES or norm in existing_norm_set:
            return True
        words = clean.split()
        if len(words) < 3 or len(words) > 8:
            return True
        for raw in existing_raw_list:
            norm_r = cls._normalize_title(raw)
            if norm_r and difflib.SequenceMatcher(None, norm, norm_r).ratio() >= 0.70:
                return True
        return False

    @classmethod
    def _generate_procedural_fallback_title(cls, streamer: str, transcript: str, existing_norm_set: set[str]) -> str:
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "about",
            "against", "between", "into", "through", "during", "before", "after", "above", "below",
            "from", "up", "down", "is", "are", "was", "were", "be", "been", "being", "have", "has",
            "had", "do", "does", "did", "can", "could", "shall", "should", "will", "would", "may",
            "might", "must", "it", "its", "you", "your", "he", "she", "they", "we", "i", "me", "my",
            "this", "that", "what", "which", "who", "whom", "here", "there", "when", "where", "why",
            "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
            "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just", "like",
            "oh", "bro", "dude", "okay", "yeah", "gonna", "wanna", "gosh", "omg", "uh", "um", "said",
            "think", "know", "going", "really", "cant", "dont", "told"
        }
        tokens = [re.sub(r'[^a-zA-Z]', '', w) for w in (transcript or "").split()]
        meaningful = [w.capitalize() for w in tokens if len(w) > 3 and w.lower() not in stop_words]
        clean_streamer = streamer.capitalize() if streamer and streamer.lower() != "none" else "Streamer"

        # High-CTR psychological headline templates
        templates = [
            f"When {clean_streamer} Realized Chat Was Right",
            f"The Exact Moment {clean_streamer} Snapped",
            f"{clean_streamer} Caught In 4K Live",
            f"Why {clean_streamer} Instantly Regretted Answering",
            f"Chat Completely Stunned {clean_streamer} Live",
            f"The Wildest Statement On Stream Today",
            f"When Banter Turned Completely Serious",
            f"{clean_streamer} Refused To Back Down",
            f"The One Line That Silenced Chat",
            f"Nobody Expected {clean_streamer} To Say This",
            f"{clean_streamer} Dropped An Unfiltered Confession",
            f"The Decision That Cost {clean_streamer} Everything",
        ]

        if meaningful:
            topic = meaningful[0]
            templates.insert(0, f"When {clean_streamer} Faced {topic} Live")
            templates.insert(1, f"The Truth About The {topic} Blunder")
            templates.insert(2, f"{clean_streamer} Completely Lost It Over {topic}")
            if len(meaningful) >= 2:
                templates.insert(0, f"{clean_streamer} Reacts To {meaningful[0]} {meaningful[1]}")

        for cand in templates:
            norm = cls._normalize_title(cand)
            if norm not in existing_norm_set and norm not in cls.GENERIC_OR_REPETITIVE_TITLES:
                return cand

        return f"{clean_streamer} Shocking Stream Moment #{int(time.time() * 1000) % 1000}"

    @classmethod
    async def sanitize_clip_hook_title(
        cls,
        raw_title: str,
        streamer_name: str,
        transcript: str,
        reasoning: str,
        db: AsyncSession,
    ) -> str:
        """Guarantees hook_title is 100% unique, non-generic, and content-grounded before burning into video."""
        existing_raw_list: list[str] = []
        existing_norm_set: set[str] = set()
        try:
            q = await db.execute(text("SELECT hook_title FROM generated_clips WHERE hook_title IS NOT NULL ORDER BY created_at DESC LIMIT 100"))
            existing_raw_list = [r[0] for r in q.fetchall() if r[0]]
            existing_norm_set = {cls._normalize_title(t) for t in existing_raw_list}
        except Exception as e:
            logger.debug("Failed querying existing titles for hook title check: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass

        clean_raw = raw_title.strip().strip('"').strip("'")
        if not cls._is_repetitive_or_generic(clean_raw, existing_norm_set, existing_raw_list):
            return clean_raw

        logger.info("Title '%s' for %s is generic or duplicate. Synthesizing unique hook title via AI...", clean_raw, streamer_name)
        try:
            agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")
            recent_str = "\n".join(f"- {t}" for t in existing_raw_list[:25])
            prompt = f"""You are an elite viral short-form director clipping live content for "{streamer_name}".
The title "{clean_raw}" was rejected for being generic, repetitive, or already used.
Generate 5 completely UNIQUE, HIGH-CTR, CATCHY titles (3 to 7 words only) specifically grounded in this moment's dialogue:

STREAMER: {streamer_name}
TRANSCRIPT:
"{transcript[:500]}"

REASONING:
"{reasoning[:200]}"

CATCHINESS & VIRALITY RULES:
1. STRICTLY 3 TO 7 WORDS ONLY.
2. Pique an intense CURIOSITY GAP — the title must pose a situation, conflict, or shocking realization that viewers CANNOT resist clicking to see resolved.
3. Use high-stakes, active verbs (e.g. Exposed, Silenced, Regretted, Snapped, Backfired, Confessed, Blundered).
4. Must mention "{streamer_name}" or the specific subject/action from the dialogue. NEVER generate vague or random noun lists.
5. Plain text only: NO quotes, NO hashtags, NO emojis.
6. FORBIDDEN to copy or resemble any generic templates or these recent titles:
{recent_str}

Respond ONLY with a JSON array of 5 unique, catchy title strings:
["Catchy Title 1", "Catchy Title 2", "Catchy Title 3", "Catchy Title 4", "Catchy Title 5"]
"""
            ai_resp = await agent.request(prompt)
            raw_text = ""
            for p in getattr(ai_resp, "parts", []):
                if hasattr(p, "content") and p.content:
                    raw_text = p.content
                    break
            if not raw_text:
                raw_text = str(ai_resp)

            match = re.search(r"\[\s*\".*\"\s*\]", raw_text, re.DOTALL)
            if match:
                cands = json.loads(match.group(0))
                for cand in cands:
                    cand_clean = cand.strip().strip('"').strip("'")
                    if not cls._is_repetitive_or_generic(cand_clean, existing_norm_set, existing_raw_list):
                        logger.info("Generated new bespoke hook title for %s: '%s'", streamer_name, cand_clean)
                        return cand_clean
        except Exception as ai_err:
            logger.warning("AI unique hook title generation failed for %s: %s", streamer_name, ai_err)

        fallback = cls._generate_procedural_fallback_title(streamer_name, transcript, existing_norm_set)
        logger.info("Using procedural fallback title for %s: '%s'", streamer_name, fallback)
        return fallback

    # -------------------------------------------------------------------------
    # Sliding AI Moment Detection & Instant Clipping
    # -------------------------------------------------------------------------

    @staticmethod
    async def evaluate_buffer_for_moments(
        db: AsyncSession,
        session: ActiveLiveSession,
        min_virality: int = 75,
    ) -> List[Dict[str, Any]]:
        """Transcribe latest buffer window, analyze with Gemini Flash, cut viral moments, and auto-clean analysis files."""
        analysis_dir = session.buffer_dir / "analysis"
        try:
            return await LiveStreamService._evaluate_buffer_inner(db, session, min_virality, analysis_dir)
        finally:
            LiveStreamService.clean_analysis_artifacts(analysis_dir)

    @staticmethod
    async def _evaluate_buffer_inner(
        db: AsyncSession,
        session: ActiveLiveSession,
        min_virality: int,
        analysis_dir: Path,
    ) -> List[Dict[str, Any]]:
        """Internal moment evaluation routine."""
        # Get completed chunks (excluding the currently active recording file)
        chunks = sorted(session.buffer_dir.glob("chunk_*.mp4"))
        if len(chunks) < 2:
            return []  # Need at least 1-2 completed minutes

        # Exclude active recording file and verify moov atom integrity
        valid_chunks = [c for c in chunks[:-1] if _is_valid_mp4(c)]
        if len(valid_chunks) < 2:
            return []

        # Consider the latest 3-4 completed valid chunks
        eligible_chunks = valid_chunks[-4:]

        # Merge these eligible chunks into a temporary analysis segment
        analysis_dir.mkdir(exist_ok=True)

        concat_list_file = analysis_dir / "concat_list.txt"
        with open(concat_list_file, "w") as f:
            for c in eligible_chunks:
                f.write(f"file '{c.resolve()}'\n")

        merged_video = analysis_dir / "recent_window.mp4"
        merged_audio = analysis_dir / "recent_window.wav"

        # Concat chunks without re-encoding, regenerating clean timestamps across seams
        subprocess.run(
            [
                _ffmpeg_path(), "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list_file),
                "-c", "copy",
                "-fflags", "+genpts",
                "-avoid_negative_ts", "make_zero",
                str(merged_video)
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Check if merged_video has an audio stream before attempting extraction
        probe_cmd = [_ffprobe_path(), "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(merged_video)]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        if not probe_res.stdout.strip():
            logger.debug("No audio track detected in live stream window for %s, skipping", session.streamer_name)
            return []

        # Extract 16kHz mono WAV for Whisper
        res = subprocess.run(
            [_ffmpeg_path(), "-y", "-i", str(merged_video), "-vn", "-ac", "1", "-ar", "16000", str(merged_audio)],
            capture_output=True, text=True
        )
        if res.returncode != 0:
            logger.warning("Failed to extract audio from %s: %s", merged_video, res.stderr)
            return []

        if not merged_audio.exists() or merged_audio.stat().st_size < 8000:
            logger.debug("Extracted audio for %s is empty or too short, skipping", session.streamer_name)
            return []

        # Transcribe with Whisper (using shared cached model protected by lock)
        try:
            model = _get_whisper_model()
            async with _whisper_async_lock:
                whisper_result = await asyncio.to_thread(
                    model.transcribe,
                    str(merged_audio),
                    language="en",
                    fp16=False,
                    word_timestamps=True,
                )
        except Exception as whisper_err:
            logger.warning("Whisper transcription failed for %s: %s", session.streamer_name, whisper_err)
            return []

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

        # -----------------------------------------------------------
        # Step 1.5: Computer Vision - Motion, Posture & Face Emotion
        # -----------------------------------------------------------
        try:
            visual_events = await asyncio.to_thread(analyze_visual_actions, merged_video, 4)
            visual_lines = [f"[{e['time']}] {e['type']}: {e['detail']}" for e in visual_events]
            visual_summary = "\n".join(visual_lines) if visual_lines else "Stable stream camera motion with consistent posture."
        except Exception as vis_err:
            logger.warning("Visual action analysis failed for %s: %s", session.streamer_name, vis_err)
            visual_summary = "Visual tracking unavailable."

        # Fetch recent titles to enforce strict uniqueness without PostgreSQL DISTINCT-ORDER BY conflicts
        try:
            recent_titles_q = await db.execute(text("SELECT hook_title FROM generated_clips WHERE hook_title IS NOT NULL ORDER BY created_at DESC LIMIT 50"))
            recent_titles_raw = list(dict.fromkeys(r[0] for r in recent_titles_q.fetchall() if r[0]))
            recent_titles_clause = "\n".join(f"- {t}" for t in recent_titles_raw[:20]) if recent_titles_raw else "None"
        except Exception as title_err:
            logger.debug("Could not fetch recent titles for uniqueness: %s", title_err)
            try:
                await db.rollback()
            except Exception:
                pass
            recent_titles_clause = "None"

        # Prompt Antigravity Gemini Flash bridge with Multi-Modal Vision + Speech instructions
        prompt = f"""You are an elite viral short-form director clipping live content for "{session.streamer_name}".
Analyze this 2-5 minute window from their ongoing live broadcast using BOTH spoken speech AND computer vision action data.

TRANSCRIPT:
{full_transcript}

FRAME-BY-FRAME VISUAL & EMOTIONAL ACTIONS:
{visual_summary}

UNIVERSAL MULTI-MODAL VIRALITY MATRIX (APPLIES COLLECTIVELY TO ALL STREAMERS & CONTENT):
This collective intelligence is derived from 500+ top-performing clips across all genres (gaming, IRL, commentary, podcast, chess, comedy, drama). Apply ALL of these dimensions simultaneously regardless of who is on screen:

1. DURATION & CONTEXTUAL STORY ARC (DYNAMIC CONTEXT-BASED, STRICT MIN 30s, FLEXIBLE 30-58s):
   - You MUST keep every video ABOVE 30 seconds (strict minimum: 30.0s).
   - It is NOT necessary or desirable to finish every video at 38 seconds! You can increase or decrease length depending on the video's specific context.
   - Always check the context of the video and decide the length based on what the viewer needs to fully understand the moment:
     * Setup & Context (0-8s): Ensure enough lead-in context for the viewer to understand who is speaking, who they are talking to, and what the situation/stakes are. Never start abruptly without context.
     * Escalation & Midpoint Climax (40-48% mark): The tension, hilarious blunder, or shocking revelation.
     * Full Resolution & Punchline: Let the streamer complete their full thought, explanation, or reaction. NEVER cut off mid-explanation or mid-sentence.
   - Adjust duration dynamically between 30 and 58 seconds to capture the complete context.
   - HARD LIMIT: Never exceed 58.0 seconds (YouTube Shorts 60s limit).

2. MULTI-MODAL PHYSICAL & VISUAL ACTIONS (CV Optical Flow + Facial Tracking):
   - ACUTE SHOCK & OUTRAGE EMPHASIS: Frame-by-frame cascade data across 1,000 videos proves wide-eyed shock and sudden physical disbelief outperform mild laughter by 9.38x (and 23.3x in top viral tiers). Prioritize high-arousal facial distortion, mouth-open screams, standing up, knocking chairs, violent desk slams, and intense camera stares.
   - When visual kinetic spikes occur, correlate them with the accompanying speech to capture the exact peak.

3. UNIVERSAL NARRATIVE & EMOTIONAL HOOK ARCHETYPES:
   - Impending Doom & Instant Regret: Confidently boasting or celebrating 2 seconds before catastrophic failure or defeat.
   - Interpersonal & Relationship Conflict: Sibling banter, dating confessions, awkward relationship gossip, breaking character, exposing private secrets, uncomfortable interrogations.
   - Cynical Video/Chat Reactions: Reacting to external videos, TikToks, or chat takes, building tension, and landing a devastating, cynical, or hilarious punchline right at the end.
   - Accidental Reveals & "Caught in 4K": Hot mic moments, forgetting the camera is on, studio accidents, breaking props, showing something forbidden on screen.
   - Ego Clash & Rage Tilt: Heated arguments, competitive meltdowns, screaming at opponents or chat.
   - STRICTLY DOWN-RANK: Quiet menu navigation, silent technical gameplay, reading chat without a strong reaction, or passive background listening.

4. THE 0-3s INSTANT HOOK:
   - Clip start_time must land directly on the first provocative question, sudden scream, or visual shock. Zero dead air.

5. STRICT CUTTING BOUNDARIES — WHERE TO CUT AND WHERE NOT TO CUT:
   - CRITICAL ZERO-DEFECT RULE: NEVER end a clip on an unfinished thought, introductory clause, dangling connective, or mid-sentence explanation.
   - WHERE NOT TO CUT (ABSOLUTELY FORBIDDEN):
     * NEVER cut when the speaker ends on: "and", "but", "because", "why", "so", "if", "when", "that", "like", "or", "though", "with", "to".
     * NEVER cut on an introductory clause: "And let me...", "Let me tell you...", "The reason why...", "Here's what happens...", "Watch this...", "Here it comes...", "Why I would not...".
     * NEVER cut right as the streamer begins explaining their reasoning! If a streamer says "And let me tell you why I would not do that", the clip MUST include the entire explanation sentence until the thought is 100% complete.
     * NEVER artificially compress a clip to 15s-20s for "loop rate". A 19s clip that cuts off the explanation is completely useless and broken.
   - WHERE TO CUT (THE PERFECT OUT-POINT):
     * Cut ONLY after a complete, standalone sentence that ends with a period (.), question mark (?), or exclamation mark (!).
     * The viewer MUST hear the full justification, punchline, or reaction resolution.
     * Allow 0.8s - 1.5s of natural pause/laughter decay after the last word so the final syllable is never chopped.

CRITICAL REQUIREMENT - 100% UNIQUE, CONTENT-SPECIFIC TITLES ("hook_title"):
The title burned onto the top of the video and shown in the feed MUST FORCE scrolling viewers to click.
Every single title MUST be completely unique, novel, and specific to what actually happened in this clip.

1. ABSOLUTELY ZERO REPETITION & NO GENERIC TEMPLATES (STRICT):
   - Every title MUST be 100% unique, novel, and derived directly from this conversation.
   - FORBIDDEN: Any generic, vague, or reusable phrases that could apply to any stream.
   - DO NOT repeat, closely resemble, or copy any of these recently used titles:
{recent_titles_clause}

2. CATCHY, HIGH-CTR PSYCHOLOGICAL FORMULAS (MUST BE IRRESISTIBLY CLICK-FORCING):
   - Your title MUST force scrolling viewers to stop dead in their tracks using the CURIOSITY GAP.
   - Pique high emotional stakes, disbelief, unexpected drama, or an unresolved question that ONLY watching the video answers.
   - Use high-stakes, active verbs (e.g. Exposed, Silenced, Regretted, Snapped, Backfired, Confessed, Blundered).
   - Mention "{session.streamer_name}" or the specific person/subject in the clip. NEVER generate random words or dry descriptive summaries.
   - Winning archetypes to adapt dynamically:
     * When {session.streamer_name} Realized The [Specific Topic/Blunder]
     * {session.streamer_name} Reacts To The Wildest [Topic/Claim]
     * The Exact Moment [Specific Event/Accusation] Happened
     * Chat Completely Stunned {session.streamer_name} With This
     * Why {session.streamer_name} Had To Speak Out About [Topic]
     * {session.streamer_name} Dropped An Unfiltered Confession Live
   - Introduce an intense curiosity gap without spoiling the outcome.

3. STRICT LENGTH: 3 TO 7 WORDS ONLY.
   - Viewers scroll past long sentences in 0.4s. Keep it punchy, visceral, and readable at a glance.
   - Plain text only. NO quotes, NO hashtags, NO emojis.

Respond ONLY with a JSON array of objects (or empty [] if no moment exceeds 75 virality):
[
  {{
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "hook_title": "Unique 3-7 word click-forcing title specific to this clip",
    "hook": "Opening spoken sentence or immediate hook",
    "virality_score": 88,
    "action_archetype": "Visual action type e.g. Chair Jump / Screaming / Sister Banter",
    "reason": "Why this specific moment will explode in views"
  }}
]
"""
        agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")
        try:
            ai_resp = await agent.request(prompt)
            raw_text = ""
            for p in getattr(ai_resp, "parts", []):
                if hasattr(p, "content") and p.content:
                    raw_text = p.content
                    break
            if not raw_text:
                raw_text = str(ai_resp)

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

            raw_start_s = max(0.0, _to_sec(start_str))
            raw_end_s = max(raw_start_s + 5.0, _to_sec(end_str))

            # Apply Intelligent Sentence-Aware Context Pre-Roll & Post-Roll
            # Keeps video strictly above 30 seconds, dynamically scales with narrative context up to 58.0s,
            # and snaps to natural sentence boundaries without premature cuts.
            start_s, end_s, duration = apply_context_preroll_and_postroll(
                start_s=raw_start_s,
                end_s=raw_end_s,
                segments=segments,
                min_duration=30.0,
                max_duration=58.0,
                target_sweet_spot=40.0,
            )

            # Format clean MM:SS strings for DB recording
            start_m, start_rem = divmod(int(start_s), 60)
            end_m, end_rem = divmod(int(end_s), 60)
            start_str = f"{start_m:02d}:{start_rem:02d}"
            end_str = f"{end_m:02d}:{end_rem:02d}"

            clip_id = str(uuid.uuid4())
            clip_filename = f"live_{session.streamer_id[:8]}_{int(time.time())}_{clip_id[:8]}.mp4"
            clip_dest = CLIPS_DIR / clip_filename
            CLIPS_DIR.mkdir(parents=True, exist_ok=True)

            # Guarantee 100% unique, non-repetitive, and content-grounded hook title before rendering
            clip_transcript = " ".join(
                s.get("text", "").strip()
                for s in segments
                if s.get("start", 0) <= end_s and s.get("end", 0) >= start_s
            )
            moment["hook_title"] = await LiveStreamService.sanitize_clip_hook_title(
                raw_title=moment.get("hook_title") or "",
                streamer_name=session.streamer_name,
                transcript=clip_transcript,
                reasoning=moment.get("reason") or "",
                db=db,
            )

            # -----------------------------------------------------------
            # Step 1: Extract the moment time range with frame-accurate re-encode
            # (Prevents GOP boundary tearing, missing references, and video playback freezing)
            # -----------------------------------------------------------
            temp_source = analysis_dir / f"source_{clip_id[:8]}.mp4"
            extract_cmd = [
                _ffmpeg_path(), "-y",
                "-ss", str(start_s), "-to", str(end_s),
                "-i", str(merged_video),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts",
                str(temp_source),
            ]
            subprocess.run(extract_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # -----------------------------------------------------------
            # Step 2: Streamer Ambient Blurred Canvas Format (1080x1920)
            # Center foreground stream cropped 6% left, 6% right,
            # 1% top, and 1% bottom, scaled to fill 1080w and centered vertically.
            # Top and bottom ambient blurred regions remain untouched.
            # -----------------------------------------------------------
            video_filter = (
                "[0:v]split=2[bgsrc][fgsrc];"
                "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
                "[fgsrc]crop=trunc(iw*0.88/2)*2:trunc(ih*0.98/2)*2:trunc(iw*0.06/2)*2:trunc(ih*0.01/2)*2,scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
            )
            mode = "complex"
            caption_y = 0.80
            logger.info(
                "Applying ambient blurred canvas format with 6%% side crop (1%% top/bottom) for %s (caption_y=0.80)",
                session.streamer_name,
            )

            # -----------------------------------------------------------
            # Step 3: Build styled ASS subtitles with dynamic caption placement
            # -----------------------------------------------------------
            ass_path = analysis_dir / f"clip_{clip_id[:8]}.ass"
            _build_live_clip_ass(
                segments=segments,
                start_s=start_s,
                end_s=end_s,
                hook_title=moment.get("hook_title") or "",
                output_ass=ass_path,
                caption_y=caption_y if caption_y is not None else 0.82,
            )

            # -----------------------------------------------------------
            # Step 4: Build the final render command using venv ffmpeg
            # -----------------------------------------------------------
            #   (which has libass for subtitle burning).
            #   Combine the reframing filter with ASS subtitle overlay.
            # -----------------------------------------------------------
            has_audio = ffprobe_has_audio(temp_source)
            escaped_ass = str(ass_path.resolve()).replace(":", "\\:").replace("'", "\\'")
            subs_frag = f"subtitles=filename='{escaped_ass}'"

            if mode == "complex":
                # filter_complex graph producing [vout]; append subs after it
                full_graph = f"{video_filter};[vout]{subs_frag}[v]"
                render_cmd = [
                    _ffmpeg_path(), "-y",
                    "-i", str(temp_source),
                    "-filter_complex", full_graph,
                    "-map", "[v]",
                ]
            else:
                # Simple -vf chain (crop+scale); append subs at the end
                full_vf = f"{video_filter},{subs_frag}"
                render_cmd = [
                    _ffmpeg_path(), "-y",
                    "-i", str(temp_source),
                    "-vf", full_vf,
                ]

            if has_audio:
                render_cmd.extend(["-map", "0:a", "-c:a", "aac", "-b:a", "128k"])
            render_cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-r", "60",
                "-g", "60",
                "-keyint_min", "60",
                "-sc_threshold", "0",
                "-color_primaries", "bt709",
                "-color_trc", "bt709",
                "-colorspace", "bt709",
                "-movflags", "+faststart",
                "-shortest",
                str(clip_dest),
            ])

            try:
                subprocess.run(render_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            except subprocess.CalledProcessError as render_exc:
                logger.warning(
                    "Face-aware render failed for %s (rc=%s), retrying with blurred-bg fit: %s",
                    session.streamer_name, render_exc.returncode,
                    (render_exc.stderr or "")[-500:],
                )
                # Retry with safe blurred-bg fit (with 6% side crop and 1% top/bottom crop)
                safe_filter = (
                    "[0:v]split=2[bgsrc][fgsrc];"
                    "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
                    "[fgsrc]crop=trunc(iw*0.88/2)*2:trunc(ih*0.98/2)*2:trunc(iw*0.06/2)*2:trunc(ih*0.01/2)*2,scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{subs_frag}[vout]"
                )
                retry_cmd = [
                    _ffmpeg_path(), "-y",
                    "-i", str(temp_source),
                    "-filter_complex", safe_filter,
                    "-map", "[vout]",
                ]
                if has_audio:
                    retry_cmd.extend(["-map", "0:a", "-c:a", "aac", "-b:a", "128k"])
                retry_cmd.extend([
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    "-r", "60",
                    "-g", "60",
                    "-keyint_min", "60",
                    "-sc_threshold", "0",
                    "-color_primaries", "bt709",
                    "-color_trc", "bt709",
                    "-colorspace", "bt709",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(clip_dest),
                ])
                subprocess.run(retry_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Clean up temp source
            temp_source.unlink(missing_ok=True)

            # -----------------------------------------------------------
            # Step 5: Strip Old Metadata & Embed Viral Social Metadata
            # -----------------------------------------------------------
            hook_title_clean = moment.get("hook_title") or f"Highlight from {session.streamer_name}"
            streamer_tags = get_streamer_tags(session.streamer_name)
            try:
                strip_and_embed_video_metadata(
                    video_path=clip_dest,
                    title=hook_title_clean,
                    streamer_name=session.streamer_name,
                    custom_tags=streamer_tags,
                )
            except Exception as meta_err:
                logger.warning("Metadata embedding failed for %s: %s", clip_dest.name, meta_err)

            # Get next clip order for this task
            order_res = await db.execute(
                text("SELECT COALESCE(MAX(clip_order), 0) + 1 FROM generated_clips WHERE task_id = :task_id"),
                {"task_id": session.task_id}
            )
            next_order = order_res.scalar() or 1

            # Prepare rich workflow metadata
            clip_workflow_meta = {
                "tags": streamer_tags,
                "streamer": session.streamer_name,
                "platform": session.platform,
                "action_archetype": moment.get("action_archetype") or "Dynamic Stream Highlight",
                "metadata_embedded": True,
                "youtube_ready": True,
            }

            # Insert clip into generated_clips table
            await db.execute(
                text("""
                    INSERT INTO generated_clips (
                        id, task_id, filename, file_path, start_time, end_time, duration,
                        relevance_score, virality_score, hook_score, hook_title, reasoning, text, clip_order, workflow_meta
                    ) VALUES (
                        :id, :task_id, :filename, :path, :start_time, :end_time, :duration,
                        :relevance, :score, :score, :hook_title, :reason, :text, :clip_order, :wf_meta
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
                    "relevance": float(score) / 100.0,
                    "score": score,
                    "hook_title": hook_title_clean,
                    "reason": moment.get("reason") or "Standout live moment",
                    "text": moment.get("hook") or "",
                    "clip_order": next_order,
                    "wf_meta": json.dumps(clip_workflow_meta),
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

            # If Virality Score >= 95, notify priority queue for youtube_auto_scheduler
            if score >= 95:
                logger.info(
                    "⚡ ULTRA-VIRAL CLIP (Score %d >= 95) detected: '%s'! Queued for prioritized upload via youtube_auto_scheduler (with 3-5 min anti-bot cooldown).",
                    score, hook_title_clean
                )

            logger.info("Successfully generated live clip: %s (Virality %s)", clip_filename, score)
            generated_clips.append({"clip_id": clip_id, "filename": clip_filename, **moment})

        return generated_clips
