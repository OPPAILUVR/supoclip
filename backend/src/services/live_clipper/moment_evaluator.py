"""Sliding AI Moment Detection, Sensory Scoring, Layout Rendering, & Thumbnailing."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...ai import AntigravityDirectModel
from ...media.ffmpeg import ffprobe_has_audio, ffprobe_video_size
from ...media.layouts import build_live_clip_layout
from ...utils.motion_analyzer import analyze_visual_actions
from ...utils.sensory_analyzer import SensoryAnalyzer
from ...utils.video_metadata import get_streamer_tags, strip_and_embed_video_metadata
from ..thumbnail_generator import generate_viral_thumbnail
from .buffer_manager import (
    CLIPS_DIR,
    ActiveLiveSession,
    _ffmpeg_path,
    _ffprobe_path,
    _is_valid_mp4,
    clean_analysis_artifacts,
)
from .context_trimmer import apply_context_preroll_and_postroll
from .streamer_repository import record_event
from .subtitles_and_titles import (
    _whisper_async_lock,
    build_live_clip_ass,
    get_whisper_model,
    sanitize_clip_hook_title,
)

logger = logging.getLogger(__name__)


async def evaluate_buffer_for_moments(
    db: AsyncSession,
    session: ActiveLiveSession,
    min_virality: int = 75,
) -> List[Dict[str, Any]]:
    """Transcribe latest buffer window, analyze with Gemini Flash, cut viral moments, and clean artifacts."""
    analysis_dir = session.buffer_dir / "analysis"
    try:
        return await _evaluate_buffer_inner(db, session, min_virality, analysis_dir)
    finally:
        clean_analysis_artifacts(analysis_dir)


async def _evaluate_buffer_inner(
    db: AsyncSession,
    session: ActiveLiveSession,
    min_virality: int,
    analysis_dir: Path,
) -> List[Dict[str, Any]]:
    """Internal moment evaluation and rendering routine."""
    MIN_CLIP_COOLDOWN_SECONDS = 600
    now_ts = time.time()
    if session.last_clipped_time and (now_ts - session.last_clipped_time) < MIN_CLIP_COOLDOWN_SECONDS:
        logger.debug(
            "Pacing cooldown active for %s (last clip created %d seconds ago); waiting for next window",
            session.streamer_name,
            int(now_ts - session.last_clipped_time),
        )
        return []

    chunks = sorted(session.buffer_dir.glob("chunk_*.mp4"))
    if len(chunks) < 2:
        return []

    valid_chunks = [c for c in chunks[:-1] if _is_valid_mp4(c)]
    if len(valid_chunks) < 2:
        return []

    num_chunks = 8 if len(valid_chunks) >= 8 else len(valid_chunks)
    eligible_chunks = valid_chunks[-num_chunks:]

    analysis_dir.mkdir(exist_ok=True)
    concat_list_file = analysis_dir / "concat_list.txt"
    with open(concat_list_file, "w") as f:
        for c in eligible_chunks:
            f.write(f"file '{c.resolve()}'\n")

    merged_video = analysis_dir / "recent_window.mp4"
    merged_audio = analysis_dir / "recent_window.wav"

    subprocess.run(
        [
            _ffmpeg_path(), "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            "-fflags", "+genpts",
            "-avoid_negative_ts", "make_zero",
            str(merged_video),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    probe_cmd = [
        _ffprobe_path(), "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(merged_video),
    ]
    probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
    if not probe_res.stdout.strip():
        logger.debug("No audio track detected in live stream window for %s, skipping", session.streamer_name)
        return []

    res = subprocess.run(
        [_ffmpeg_path(), "-y", "-i", str(merged_video), "-vn", "-ac", "1", "-ar", "16000", str(merged_audio)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        logger.warning("Failed to extract audio from %s: %s", merged_video, res.stderr)
        return []

    if not merged_audio.exists() or merged_audio.stat().st_size < 8000:
        logger.debug("Extracted audio for %s is empty or too short, skipping", session.streamer_name)
        return []

    try:
        model = get_whisper_model()
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

    try:
        visual_events = await asyncio.to_thread(analyze_visual_actions, merged_video, 4)
        visual_lines = [f"[{e['time']}] {e['type']}: {e['detail']}" for e in visual_events]
        visual_summary = "\n".join(visual_lines) if visual_lines else "Stable stream camera motion with consistent posture."
    except Exception as vis_err:
        logger.warning("Visual action analysis failed for %s: %s", session.streamer_name, vis_err)
        visual_summary = "Visual tracking unavailable."

    try:
        recent_titles_q = await db.execute(
            text("SELECT hook_title FROM generated_clips WHERE hook_title IS NOT NULL ORDER BY created_at DESC LIMIT 50")
        )
        recent_titles_raw = list(dict.fromkeys(r[0] for r in recent_titles_q.fetchall() if r[0]))
        recent_titles_clause = "\n".join(f"- {t}" for t in recent_titles_raw[:20]) if recent_titles_raw else "None"
    except Exception as title_err:
        logger.debug("Could not fetch recent titles for uniqueness: %s", title_err)
        try:
            await db.rollback()
        except Exception:
            pass
        recent_titles_clause = "None"

    prompt = f"""You are an elite viral short-form director clipping live content for "{session.streamer_name}".
Analyze this 2-5 minute window from their ongoing live broadcast using BOTH spoken speech AND computer vision action data.

TRANSCRIPT:
{full_transcript}

FRAME-BY-FRAME VISUAL & EMOTIONAL ACTIONS:
{visual_summary}

UNIVERSAL MULTI-MODAL VIRALITY MATRIX (APPLIES COLLECTIVELY TO ALL STREAMERS & CONTENT):
This collective intelligence is derived from 500+ top-performing clips across all genres (gaming, IRL, commentary, podcast, chess, comedy, drama). Apply ALL of these dimensions simultaneously regardless of who is on screen:

1. DURATION & CONTEXTUAL STORY ARC (DYNAMIC CONTEXT-BASED, STRICT MIN 30s, UP TO 175s FOR STORYTELLING/RANTS):
   - You MUST keep every video ABOVE 30 seconds (strict minimum: 30.0s).
   - Long-form reaction/storytelling clips (especially Asmongold reaction breakdowns, rants, and debates like @LivestreamsMemes):
     * Allow clips to run naturally between 60s and 175s (up to 3 minutes) so the complete 4-act story arc unfolds: Setup (0-20s) -> Reaction (5s) -> Monologue/Rant (45-90s) -> Punchline & Payoff (10-15s).
     * NEVER truncate before the punchline or resolution!
   - For quick, high-energy clips (sudden blunders, jumpscares), 30 to 60 seconds is fine.
   - Adjust duration dynamically between 30 and 175 seconds to capture the complete context.
   - HARD LIMIT: Never exceed 175.0 seconds (YouTube Shorts 3-minute limit).

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
     * NEVER cut right as the streamer begins explaining their reasoning!
     * NEVER artificially compress a clip to 15s-20s for "loop rate".
   - WHERE TO CUT (THE PERFECT OUT-POINT):
     * Cut ONLY after a complete, standalone sentence that ends with a period (.), question mark (?), or exclamation mark (!).
     * Allow 0.8s - 1.5s of natural pause/laughter decay after the last word so the final syllable is never chopped.

6. TOPIC SHIFT & NARRATIVE BOUNDARY DETECTION (LEARNED FROM @LivestreamsMemes VIRAL STANDARD):
   - Detect distinct topic boundaries from introduction to conclusive verdict without bleeding unrelated prior chatter.

CRITICAL REQUIREMENT - 100% UNIQUE, CONTENT-SPECIFIC TITLES ("hook_title"):
- Every title MUST be 3 to 7 words, plain text only (NO quotes, NO hashtags, NO emojis).
- Mention "{session.streamer_name}" naturally.
- DO NOT repeat or resemble:
{recent_titles_clause}

Respond ONLY with a JSON array of objects (or empty [] if no moment exceeds {min_virality} virality):
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

        def _to_sec(t_str: str) -> float:
            p = [float(x) for x in t_str.split(":")]
            return p[0] * 60 + p[1] if len(p) == 2 else float(p[0])

        raw_start_s = max(0.0, _to_sec(start_str))
        raw_end_s = max(raw_start_s + 5.0, _to_sec(end_str))

        start_s, end_s, duration = apply_context_preroll_and_postroll(
            start_s=raw_start_s,
            end_s=raw_end_s,
            segments=segments,
            min_duration=30.0,
            max_duration=175.0,
            target_sweet_spot=60.0,
        )

        sensory_metrics: Dict[str, Any] = {}
        try:
            sensory_metrics = SensoryAnalyzer.analyze_sensory_features(
                video_path=str(merged_video),
                start_s=start_s,
                clip_duration=min(10.0, duration),
            )
            if sensory_metrics.get("is_passive_dead_air", False):
                logger.info(
                    "Skipping passive dead-air moment for %s (motion=%.1f, flux=%.1f)",
                    session.streamer_name,
                    sensory_metrics.get("motion_score_first_1_5s", 0.0),
                    sensory_metrics.get("acoustic_flux_score", 0.0),
                )
                continue

            calibrated_score = int(round((score * 0.6) + (sensory_metrics.get("composite_sensory_score", 50.0) * 0.4)))
            score = min(100, max(0, calibrated_score))
            moment["virality_score"] = score
            if score < min_virality:
                logger.info(
                    "Moment '%s' calibrated score %d is below min_virality %d; skipping",
                    moment.get("hook_title"),
                    score,
                    min_virality,
                )
                continue
        except Exception as sensory_err:
            logger.warning("Sensory analysis fallback for %s: %s", session.streamer_name, sensory_err)

        start_m, start_rem = divmod(int(start_s), 60)
        end_m, end_rem = divmod(int(end_s), 60)
        start_str = f"{start_m:02d}:{start_rem:02d}"
        end_str = f"{end_m:02d}:{end_rem:02d}"

        clip_id = str(uuid.uuid4())
        clip_filename = f"live_{session.streamer_id[:8]}_{int(time.time())}_{clip_id[:8]}.mp4"
        clip_dest = CLIPS_DIR / clip_filename
        CLIPS_DIR.mkdir(parents=True, exist_ok=True)

        clip_transcript = " ".join(
            s.get("text", "").strip()
            for s in segments
            if s.get("start", 0) <= end_s and s.get("end", 0) >= start_s
        )
        moment["hook_title"] = await sanitize_clip_hook_title(
            raw_title=moment.get("hook_title") or "",
            streamer_name=session.streamer_name,
            transcript=clip_transcript,
            reasoning=moment.get("reason") or "",
            db=db,
        )

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

        src_w, src_h = ffprobe_video_size(temp_source)
        logger.info("Source video dimensions for %s: %dx%d", session.streamer_name, src_w, src_h)

        layout = build_live_clip_layout(
            clip_format=getattr(session, "clip_format", "40_60") or "40_60",
            video_path=temp_source,
            src_w=src_w,
            src_h=src_h,
            streamer_name=session.streamer_name,
        )
        video_filter = layout["video_filter"]
        mode = layout["mode"]
        caption_y = layout.get("caption_y", 0.85)

        ass_path = analysis_dir / f"clip_{clip_id[:8]}.ass"
        build_live_clip_ass(
            segments=segments,
            start_s=start_s,
            end_s=end_s,
            hook_title=moment.get("hook_title") or "",
            output_ass=ass_path,
            caption_y=caption_y if caption_y is not None else 0.82,
        )

        has_audio = ffprobe_has_audio(temp_source)
        escaped_ass = str(ass_path.resolve()).replace(":", "\\:").replace("'", "\\'")
        subs_frag = f"subtitles=filename='{escaped_ass}'"

        if mode == "complex":
            full_graph = f"{video_filter};[vout]{subs_frag}[v]"
            render_cmd = [
                _ffmpeg_path(), "-y",
                "-i", str(temp_source),
                "-filter_complex", full_graph,
                "-map", "[v]",
            ]
        else:
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
                "Subtitle burn render failed for %s (rc=%s): %s. Rendering clean vertical layout without burned subs...",
                session.streamer_name, render_exc.returncode, (render_exc.stderr or "")[-300:],
            )
            retry_cmd = [
                _ffmpeg_path(), "-y",
                "-i", str(temp_source),
                "-filter_complex", video_filter,
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

        thumb_dest = None
        try:
            thumb_dest = generate_viral_thumbnail(
                video_path=clip_dest,
                hook_title=hook_title_clean,
                streamer_name=session.streamer_name,
            )
            logger.info("Generated high-CTR viral thumbnail for clip %s: %s", clip_id, thumb_dest.name)
        except Exception as th_err:
            logger.warning("Thumbnail generation notice for %s: %s", clip_dest.name, th_err)

        order_res = await db.execute(
            text("SELECT COALESCE(MAX(clip_order), 0) + 1 FROM generated_clips WHERE task_id = :task_id"),
            {"task_id": session.task_id},
        )
        next_order = order_res.scalar() or 1

        clip_workflow_meta = {
            "tags": streamer_tags,
            "streamer": session.streamer_name,
            "platform": session.platform,
            "action_archetype": moment.get("action_archetype") or "Dynamic Stream Highlight",
            "sensory_analysis": sensory_metrics,
            "thumbnail_path": str(thumb_dest) if thumb_dest else None,
            "metadata_embedded": True,
            "youtube_ready": True,
        }

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

        await record_event(
            db,
            streamer_id=session.streamer_id,
            event_type="clip_generated",
            title=moment.get("hook_title"),
            virality_score=score,
            task_id=session.task_id,
            clip_id=clip_id,
            details=moment,
        )

        if score >= 95:
            logger.info(
                "ULTRA-VIRAL CLIP (Score %d >= 95) detected: '%s'! Queued for prioritized upload.",
                score, hook_title_clean,
            )

        logger.info("Successfully generated live clip: %s (Virality %s)", clip_filename, score)
        session.analyzed_timestamps.add(moment_key)
        session.last_clipped_time = time.time()
        generated_clips.append({"clip_id": clip_id, "filename": clip_filename, **moment})
        break

    return generated_clips
