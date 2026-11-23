#!/usr/bin/env python3
"""
YouTube Automated Humanized Scheduler for SupoClip.
Picks the highest virality-score clip every ~2 hours with randomized Gaussian/uniform jitter
to prevent bot detection / shadowbanning.
"""

import sys
import os
import re
import difflib
import time
import random
import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from src.utils.video_metadata import (
    strip_and_embed_video_metadata,
    get_streamer_tags,
    build_viral_youtube_description,
    get_streamer_profile,
)
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [YouTubeScheduler]: %(message)s",
    handlers=[
        logging.FileHandler(str(BACKEND_DIR / "youtube_uploader.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("YouTubeScheduler")

DB_URL = "postgresql+asyncpg://luv@localhost:5432/supoclip"

POST_UPLOAD_VERIFY_DELAY_SECONDS = int(os.environ.get("POST_UPLOAD_VERIFY_DELAY_SECONDS", 300)) # 5 minutes default
MAX_POST_UPLOAD_RETRIES = int(os.environ.get("MAX_POST_UPLOAD_RETRIES", 3))
MIN_INSTANT_UPLOAD_COOLDOWN_SECONDS = int(os.environ.get("MIN_INSTANT_UPLOAD_COOLDOWN_SECONDS", 180)) # 3 minutes cooldown
MAX_INSTANT_UPLOAD_COOLDOWN_SECONDS = int(os.environ.get("MAX_INSTANT_UPLOAD_COOLDOWN_SECONDS", 300)) # 5 minutes cooldown

async def get_last_upload_time_from_db(engine) -> float:
    """Retrieves the timestamp of the most recent upload attempt to enforce anti-bot cooldowns."""
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("""
                SELECT MAX(EXTRACT(EPOCH FROM (workflow_meta->>'last_upload_attempt_at')::timestamptz))
                FROM generated_clips
                WHERE workflow_meta->>'last_upload_attempt_at' IS NOT NULL
            """))
            val = res.scalar()
            if val is not None:
                return float(val)
    except Exception as e:
        logger.debug("Could not query last_upload_attempt_at: %s", e)
    return 0.0

async def record_upload_attempt(engine, clip_id, title, streamer, manifest):
    """Records that an upload attempt was initiated and arms the 5-minute verification watcher."""
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_update = {
        "last_upload_attempt_at": now_iso,
        "pending_5min_verification": True,
        "verify_due_timestamp": time.time() + POST_UPLOAD_VERIFY_DELAY_SECONDS,
        "youtube_title": title,
        "streamer": streamer,
        "latest_upload_manifest": manifest
    }
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE generated_clips
                SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                WHERE id = :id
            """),
            {"id": clip_id, "update_meta": json.dumps(meta_update)}
        )
    logger.info("Recorded upload attempt for clip %s. 5-Minute verification armed.", clip_id)

async def verify_and_retry_task(engine, clip: dict, title: str, retry_count: int = 0, delay_seconds: int = POST_UPLOAD_VERIFY_DELAY_SECONDS):
    """
    ACTIVATES ONLY AFTER AN UPLOAD IS ATTEMPTED.
    Waits 5 minutes (300s), audits YouTube Studio Content headlessly to verify
    whether the video was successfully published and is public.
    If NOT published or missing/abandoned, automatically re-queues and re-uploads the video!
    """
    logger.info(
        "⏳ [5-Minute Post-Upload Verification Activated] Watcher scheduled for '%s' (Clip ID: %s). Waiting %d seconds...",
        title, clip["id"], delay_seconds
    )
    await asyncio.sleep(delay_seconds)
    
    logger.info(
        "🔍 [5-Minute Post-Upload Verification] Checking YouTube Studio now for '%s'...",
        title
    )
    uploader = HeadlessYouTubeUploader(headless=True)
    res = await uploader.verify_video_on_youtube(title)
    now_iso = datetime.now(timezone.utc).isoformat()

    if res.get("verified"):
        logger.info(
            "✅ [5-Minute Verification SUCCESS] Video '%s' is confirmed LIVE on YouTube! Public URL: %s | Status: %s",
            title, res.get("youtube_url"), res.get("status_text")
        )
        meta_update = {
            "uploaded": True,
            "verified_on_youtube": True,
            "pending_5min_verification": False,
            "verified_at": now_iso,
            "youtube_url": res.get("youtube_url"),
            "video_id": res.get("video_id"),
            "studio_status": res.get("status_text")
        }
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE generated_clips
                    SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                    WHERE id = :id
                """),
                {"id": clip["id"], "update_meta": json.dumps(meta_update)}
            )
        return True
    else:
        logger.warning(
            "❌ [5-Minute Verification FAILED] Video '%s' was NOT found or failed processing on YouTube! (Reason: %s)",
            title, res.get("reason") or res.get("error") or "not_public"
        )
        meta_update = {
            "uploaded": False,
            "verified_on_youtube": False,
            "pending_5min_verification": False,
            "last_verification_failed_at": now_iso,
            "verification_reason": res.get("reason") or res.get("error") or "not_found",
            "retry_count": retry_count + 1
        }
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE generated_clips
                    SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                    WHERE id = :id
                """),
                {"id": clip["id"], "update_meta": json.dumps(meta_update)}
            )

        if retry_count < MAX_POST_UPLOAD_RETRIES:
            logger.info(
                "🔄 [AUTOMATIC RETRY TRIGGERED] Immediately re-attempting upload (Attempt #%d of %d) for '%s'...",
                retry_count + 1, MAX_POST_UPLOAD_RETRIES, title
            )
            # Re-attempt upload and re-arm verification!
            asyncio.create_task(process_single_upload_cycle(engine, clip=clip, retry_count=retry_count + 1))
        else:
            logger.error(
                "⛔ [MAX RETRIES EXCEEDED] Video '%s' failed verification %d times. Automatic retries halted for this clip.",
                title, MAX_POST_UPLOAD_RETRIES
            )
        return False

async def verify_last_queued_upload(engine) -> Dict[str, Any]:
    """
    Stand-alone verification function:
    Checks YouTube Studio for the very last video that was attempted for upload.
    If not verified as live, immediately triggers re-upload.
    """
    async with engine.connect() as conn:
        query = text("""
            SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
            FROM generated_clips
            WHERE workflow_meta->>'last_upload_attempt_at' IS NOT NULL
            ORDER BY (workflow_meta->>'last_upload_attempt_at') DESC
            LIMIT 1
        """)
        res = await conn.execute(query)
        row = res.fetchone()
        if not row:
            logger.info("No recorded upload attempts found to verify.")
            return {"verified": False, "reason": "no_upload_attempts_found"}
        
        clip = {
            "id": row[0],
            "filename": row[1],
            "file_path": Path(row[2]),
            "virality_score": row[3],
            "title": row[4],
            "workflow_meta": row[5] or {},
            "text": row[6] or "",
            "reasoning": row[7] or "",
        }
        title = clip["title"] or "Live Stream Highlight"
        uploader = HeadlessYouTubeUploader(headless=True)
        verify_res = await uploader.verify_video_on_youtube(title)
        
        if not verify_res.get("verified"):
            logger.warning("Last uploaded video '%s' is not verified on YouTube. Triggering re-upload...", title)
            asyncio.create_task(process_single_upload_cycle(engine, clip=clip, retry_count=clip["workflow_meta"].get("retry_count", 0) + 1))
        return verify_res

async def check_for_instant_viral_clip(engine):
    """Fetches any unuploaded clip with virality score >= 95 for INSTANT upload."""
    async with engine.connect() as conn:
        query = text("""
            SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
            FROM generated_clips
            WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false')
              AND (
                  workflow_meta->>'pending_5min_verification' IS NULL
                  OR workflow_meta->>'pending_5min_verification' = 'false'
                  OR (workflow_meta->>'verify_due_timestamp' IS NOT NULL AND (workflow_meta->>'verify_due_timestamp')::numeric < :now_ts)
              )
              AND virality_score >= 95
            ORDER BY virality_score DESC, created_at DESC
            LIMIT 1
        """)
        res = await conn.execute(query, {"now_ts": time.time()})
        row = res.fetchone()
        if row:
            return {
                "id": row[0],
                "filename": row[1],
                "file_path": Path(row[2]),
                "virality_score": row[3],
                "title": row[4],
                "workflow_meta": row[5] or {},
                "text": row[6] or "",
                "reasoning": row[7] or "",
            }
    return None

async def get_next_best_clip(engine):
    """Fetches the unuploaded clip with the highest virality score for scheduled batching."""
    async with engine.connect() as conn:
        query = text("""
            SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
            FROM generated_clips
            WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false')
              AND (
                  workflow_meta->>'pending_5min_verification' IS NULL
                  OR workflow_meta->>'pending_5min_verification' = 'false'
                  OR (workflow_meta->>'verify_due_timestamp' IS NOT NULL AND (workflow_meta->>'verify_due_timestamp')::numeric < :now_ts)
              )
            ORDER BY virality_score DESC, created_at DESC
            LIMIT 1
        """)
        res = await conn.execute(query, {"now_ts": time.time()})
        row = res.fetchone()
        if row:
            return {
                "id": row[0],
                "filename": row[1],
                "file_path": Path(row[2]),
                "virality_score": row[3],
                "title": row[4],
                "workflow_meta": row[5] or {},
                "text": row[6] or "",
                "reasoning": row[7] or "",
            }
    return None

async def mark_clip_uploaded(engine, clip_id, title, streamer, upload_details):
    """Marks a clip as uploaded in PostgreSQL to prevent duplicate uploads."""
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_update = {
        "uploaded": True,
        "pending_5min_verification": False,
        "uploaded_at": now_iso,
        "youtube_title": title,
        "streamer": streamer,
        **upload_details
    }
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE generated_clips
                SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                WHERE id = :id
            """),
            {"id": clip_id, "update_meta": json.dumps(meta_update)}
        )
    logger.info("Marked clip %s as uploaded at %s", clip_id, now_iso)

async def mark_clip_upload_failed(engine, clip_id, error_details):
    """Records upload failure in PostgreSQL while keeping uploaded=False so it can be retried."""
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_update = {
        "uploaded": False,
        "last_upload_attempt": now_iso,
        "upload_error": error_details.get("error") or error_details.get("status") or "failed"
    }
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE generated_clips
                SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                WHERE id = :id
            """),
            {"id": clip_id, "update_meta": json.dumps(meta_update)}
        )
    logger.warning("Marked clip %s as failed upload at %s: %s", clip_id, now_iso, meta_update["upload_error"])

async def trigger_headless_upload(video_path: Path, title: str, description: str, tags: list, streamer_name: str = ""):
    """
    Executes a 100% headless, background YouTube Studio upload via Playwright.
    Zero popups, zero screen switching, and zero interference with the user's desktop.
    Automatically generates and attaches a high-CTR viral thumbnail for every Short.
    """
    logger.info("Executing 100%% headless background upload for: %s", title)
    
    # Save upload manifest
    manifest = {
        "video_file": str(video_path),
        "title": title,
        "description": description,
        "tags": tags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "headless_playwright"
    }
    manifest_path = video_path.with_suffix(".youtube_upload.json")
    
    # Step 1.5: Automatically generate high-CTR viral thumbnail for every short
    thumbnail_path = None
    try:
        from src.services.thumbnail_generator import generate_viral_thumbnail
        thumbnail_path = generate_viral_thumbnail(
            video_path=video_path,
            hook_title=title,
            streamer_name=streamer_name
        )
        manifest["thumbnail_file"] = str(thumbnail_path)
        logger.info("Generated high-CTR viral thumbnail for upload: %s", thumbnail_path.name)
    except Exception as thumb_err:
        logger.warning("Could not generate viral thumbnail (non-fatal): %s", thumb_err)

    uploader = HeadlessYouTubeUploader(headless=True)
    auth_status = await uploader.check_auth_status()
    
    if not auth_status.get("authenticated"):
        logger.warning(
            "Headless YouTube is not authenticated yet. Video is metadata-prepped and staged at %s. "
            "Run 'python scripts/setup_youtube_auth.py --login' or supply 'youtube_cookies.json' to enable automated 1-click background publishing.",
            manifest_path
        )
        manifest["status"] = "staged_pending_auth"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        return manifest

    try:
        res = await uploader.upload_video(video_path, title, description, tags, is_short=True, thumbnail_path=thumbnail_path)
        manifest["status"] = "published"
        manifest["upload_result"] = res
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.info("Successfully published video headlessly with viral thumbnail! Result: %s", res)
        return manifest
    except Exception as e:
        logger.error("Headless upload failed: %s", e)
        manifest["status"] = "failed"
        manifest["error"] = str(e)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        return manifest

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

def _is_similar_to_existing(cand_norm: str, existing_norm_set: set, existing_raw_list: list) -> bool:
    if not cand_norm or cand_norm in existing_norm_set or cand_norm in GENERIC_OR_REPETITIVE_TITLES:
        return True
    for raw in existing_raw_list:
        norm_r = re.sub(r'[^a-zA-Z0-9]', '', raw.lower().replace('#shorts', ''))
        if norm_r and difflib.SequenceMatcher(None, cand_norm, norm_r).ratio() >= 0.70:
            return True
    return False

def _generate_procedural_unique_title(streamer: str, transcript: str, existing_norm_set: set) -> str:
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
        norm = re.sub(r'[^a-zA-Z0-9]', '', cand.lower())
        if norm not in existing_norm_set and norm not in GENERIC_OR_REPETITIVE_TITLES:
            return cand

    return f"{clean_streamer} Shocking Stream Moment #{int(time.time() * 1000) % 1000}"

async def ensure_unique_viral_title(engine, clip: dict, streamer: str) -> str:
    """
    Guarantees every single video uploaded to YouTube has a 100% unique title.
    Checks against all previously uploaded and queued YouTube titles in PostgreSQL.
    If the current title is already taken, belongs to generic repetitive templates,
    or has >= 0.70 fuzzy similarity to any existing title, uses Gemini (or intelligent
    keyword synthesis) to produce a bespoke, content-specific title from the transcript.
    """
    raw_title = (clip.get("title") or "").strip()
    norm_title = re.sub(r'[^a-zA-Z0-9]', '', raw_title.lower().replace('#shorts', ''))

    # Fetch all existing uploaded and queued titles from PostgreSQL
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT DISTINCT workflow_meta->>'youtube_title'
            FROM generated_clips
            WHERE workflow_meta->>'youtube_title' IS NOT NULL
            UNION
            SELECT DISTINCT hook_title
            FROM generated_clips
            WHERE hook_title IS NOT NULL
        """))
        uploaded_raw = [r[0] for r in res.fetchall() if r[0]]
        uploaded_norm = {re.sub(r'[^a-zA-Z0-9]', '', t.lower().replace('#shorts', '')) for t in uploaded_raw}

    is_duplicate = _is_similar_to_existing(norm_title, uploaded_norm, uploaded_raw) or len(raw_title.split()) < 3

    if not is_duplicate:
        return raw_title

    logger.info(
        "Detected repetitive/duplicate title '%s' for clip %s. Generating 100%% unique title via AI...",
        raw_title, clip["id"]
    )

    try:
        from src.ai import AntigravityDirectModel
        agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")

        prompt = f"""You are an elite YouTube Shorts title strategist.
The proposed title "{raw_title}" is a duplicate, generic template, or already used.
Generate 5 completely UNIQUE, click-compelling YouTube Shorts titles (3 to 7 words only) for this specific clip.

STREAMER: {streamer}
CLIP TRANSCRIPT / WHAT WAS SAID:
"{clip.get('text', '')[:600]}"

AI REASONING / WHAT HAPPENED:
"{clip.get('reasoning', '')[:300]}"

CRITICAL CATCHINESS & VIRALITY RULES:
1. STRICTLY 3 TO 7 WORDS ONLY.
2. Pique an intense CURIOSITY GAP — the title must pose a question, conflict, or shocking situation that viewers CANNOT resist clicking to see resolved.
3. Use high-stakes, active verbs (e.g. Exposed, Silenced, Regretted, Snapped, Backfired, Confessed, Blundered).
4. Must be specific to the actual dialogue, game, person, or reaction in THIS clip. NEVER produce random words or generic filler.
5. DO NOT repeat or closely resemble ANY of these previously used titles:
{json.dumps(uploaded_raw[-35:], indent=2)}
6. NEVER use generic template phrases or clichés.
7. Plain text only, no quotes, no emojis, no hashtags.

Respond with a JSON array of 5 unique, catchy title strings:
["Catchy Option 1", "Catchy Option 2", "Catchy Option 3", "Catchy Option 4", "Catchy Option 5"]
"""
        resp = await agent.request(prompt)
        raw_text = ""
        for p in getattr(resp, "parts", []):
            if hasattr(p, "content") and p.content:
                raw_text = p.content
                break
        if not raw_text:
            raw_text = str(resp)

        match = re.search(r"\[\s*\".*\"\s*\]", raw_text, re.DOTALL)
        if match:
            candidates = json.loads(match.group(0))
            for cand in candidates:
                cand_clean = cand.strip().strip('"').strip("'")
                cand_norm = re.sub(r'[^a-zA-Z0-9]', '', cand_clean.lower().replace('#shorts', ''))
                if not _is_similar_to_existing(cand_norm, uploaded_norm, uploaded_raw) and 3 <= len(cand_clean.split()) <= 8:
                    logger.info("Generated brand new unique title for clip %s: '%s'", clip["id"], cand_clean)
                    # Persist new title in DB
                    async with engine.begin() as conn:
                        await conn.execute(
                            text("UPDATE generated_clips SET hook_title = :title WHERE id = :id"),
                            {"title": cand_clean, "id": clip["id"]}
                        )
                    return cand_clean
    except Exception as e:
        logger.warning("AI unique title generation failed for clip %s: %s", clip["id"], e)

    # Smart procedural fallback derived from transcript words
    fallback_title = _generate_procedural_unique_title(streamer, clip.get("text", ""), uploaded_norm)
    logger.info("Using procedural fallback title for clip %s: '%s'", clip["id"], fallback_title)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE generated_clips SET hook_title = :title WHERE id = :id"),
            {"title": fallback_title, "id": clip["id"]}
        )
    return fallback_title

async def process_single_upload_cycle(engine, clip=None, retry_count: int = 0):
    """Executes an upload step for a given clip or the next best queued clip."""
    if not clip:
        clip = await get_next_best_clip(engine)
    if not clip:
        logger.info("No unuploaded clips found in database. Waiting for live monitor to generate new clips.")
        return False

    clip_path = clip["file_path"]
    if not clip_path.exists():
        logger.warning("Clip file missing on disk: %s, skipping", clip_path)
        await mark_clip_upload_failed(engine, clip["id"], {"error": "file_missing_on_disk"})
        return False

    title = clip["title"] or "Live Stream Highlight"
    # Identify streamer from filename or workflow meta
    streamer = clip["workflow_meta"].get("streamer") or "Streamer"
    if streamer == "Streamer":
        for name in ["Speed", "xQc", "Botez", "Asmongold", "Adin", "Kai"]:
            if name.lower() in title.lower() or name.lower() in clip["filename"].lower():
                streamer = name
                break

    # Guarantee 100% Unique, Non-Repetitive Title
    title = await ensure_unique_viral_title(engine, clip, streamer)
    clip["title"] = title

    tags = get_streamer_tags(streamer)
    channel_handle = clip["workflow_meta"].get("channel_handle")
    channel_url = clip["workflow_meta"].get("channel_url")

    description = build_viral_youtube_description(
        title=title,
        streamer_name=streamer,
        hook_text=clip.get("text") or "",
        reasoning=clip.get("reasoning") or "",
        channel_handle=channel_handle,
        channel_url=channel_url,
        custom_tags=tags
    )

    is_instant = clip.get("virality_score", 0) >= 95
    retry_str = f" [RETRY #{retry_count}]" if retry_count > 0 else ""
    upload_prefix = "⚡ INSTANT VIRAL UPLOAD" if is_instant else "SCHEDULED UPLOAD"
    logger.info(
        "%s%s: [%d score] \"%s\" (Streamer: %s, Path: %s)",
        upload_prefix, retry_str, clip["virality_score"], title, streamer, clip_path.name
    )

    # Step 1: Strip old encoder metadata and embed clean SEO metadata
    strip_and_embed_video_metadata(
        video_path=clip_path,
        title=title,
        streamer_name=streamer,
        custom_tags=tags,
        description=description
    )

    # Step 2: Trigger Headless Background upload with auto-generated viral thumbnail
    manifest = await trigger_headless_upload(clip_path, title, description, tags, streamer_name=streamer)

    # Step 3: Record upload attempt in DB and arm 5-minute verification watcher
    await record_upload_attempt(engine, clip["id"], title, streamer, manifest)

    upload_res = manifest.get("upload_result") or {}
    err_str = str(manifest.get("error", "")).lower()
    is_daily_limit = "daily upload limit" in err_str

    # Step 4: ACTIVATES ONLY AFTER UPLOAD ATTEMPT (unless daily limit reached):
    # Schedules 5-minute check to verify on YouTube, and if missing/failed, retries uploading!
    if not is_daily_limit:
        asyncio.create_task(
            verify_and_retry_task(
                engine=engine,
                clip=clip,
                title=title,
                retry_count=retry_count,
                delay_seconds=POST_UPLOAD_VERIFY_DELAY_SECONDS
            )
        )
    else:
        logger.warning(
            "🛑 YouTube Daily Upload Limit active for '%s'. Skipping 5-minute retry watcher.",
            title
        )

    if manifest.get("status") == "published" and upload_res.get("success"):
        return True, False
    else:
        return False, is_daily_limit

async def run_scheduler():
    logger.info("Starting Anti-Shadowban Headless YouTube Upload Scheduler (with 3-5 min cooldown on 95+ clips)...")
    engine = create_async_engine(DB_URL)
    
    last_upload_time = await get_last_upload_time_from_db(engine)
    current_instant_cooldown = random.randint(MIN_INSTANT_UPLOAD_COOLDOWN_SECONDS, MAX_INSTANT_UPLOAD_COOLDOWN_SECONDS)
    daily_limit_backoff_until = 0.0

    # Next scheduled batch upload timestamp (100-145 min)
    scheduled_upload_time = time.time() + random.randint(100, 145) * 60

    while True:
        try:
            now = time.time()

            # If daily limit was hit, sleep until backoff expires
            if now < daily_limit_backoff_until:
                remaining_limit_sleep = int(daily_limit_backoff_until - now)
                logger.info("🛑 YouTube daily upload limit active. Waiting %d seconds before re-checking quota...", remaining_limit_sleep)
                await asyncio.sleep(min(remaining_limit_sleep, 60))
                continue

            # Priority 1: Check if any clip has virality score >= 95 for prioritized upload!
            instant_clip = await check_for_instant_viral_clip(engine)
            if instant_clip:
                time_since_last = now - last_upload_time
                if time_since_last < current_instant_cooldown:
                    remaining_cooldown = int(current_instant_cooldown - time_since_last)
                    logger.info(
                        "⏳ [Anti-Bot Cooldown]: Detected 95+ viral clip '%s' (Score %d), but cooling down for %d seconds (~%.1f min) since last upload to protect channel from automation flags...",
                        instant_clip["title"], instant_clip["virality_score"], remaining_cooldown, remaining_cooldown / 60.0
                    )
                    await asyncio.sleep(min(remaining_cooldown, 15))
                    continue

                logger.info(
                    "⚡ PRIORITY UPLOAD: Detected ultra-viral clip [%d score] '%s'. Triggering upload after cooldown...",
                    instant_clip["virality_score"], instant_clip["title"]
                )
                success, is_daily_limit = await process_single_upload_cycle(engine, clip=instant_clip)
                last_upload_time = time.time()
                current_instant_cooldown = random.randint(MIN_INSTANT_UPLOAD_COOLDOWN_SECONDS, MAX_INSTANT_UPLOAD_COOLDOWN_SECONDS)

                if is_daily_limit:
                    daily_limit_backoff_until = time.time() + 3600  # 1 hour backoff
                    logger.warning("🛑 YouTube daily upload limit encountered. Backing off all uploads for 1 hour.")
                else:
                    logger.info(
                        "Enforcing %d seconds (~%.1f min) anti-bot cooldown before next upload.",
                        current_instant_cooldown, current_instant_cooldown / 60.0
                    )
                    await asyncio.sleep(current_instant_cooldown)
                continue

            # Priority 2: Check if regular scheduled time has arrived for queued clips (<95)
            if now >= scheduled_upload_time:
                time_since_last = now - last_upload_time
                if time_since_last < current_instant_cooldown:
                    await asyncio.sleep(15)
                    continue

                logger.info("Scheduled upload interval reached. Checking next best clip in queue...")
                success, is_daily_limit = await process_single_upload_cycle(engine)
                last_upload_time = time.time()
                current_instant_cooldown = random.randint(MIN_INSTANT_UPLOAD_COOLDOWN_SECONDS, MAX_INSTANT_UPLOAD_COOLDOWN_SECONDS)

                if is_daily_limit:
                    daily_limit_backoff_until = time.time() + 3600
                    logger.warning("🛑 YouTube daily upload limit encountered. Backing off all uploads for 1 hour.")
                
                # Re-arm scheduled timer
                random_minutes = random.randint(100, 145)
                scheduled_upload_time = time.time() + random_minutes * 60 + random.randint(5, 55)
                next_dt = datetime.fromtimestamp(scheduled_upload_time)
                logger.info(
                    "Next scheduled batch upload in %d min (~%.1f hrs) at %s",
                    random_minutes, random_minutes / 60.0, next_dt.strftime("%H:%M:%S")
                )

            # Sleep 15 seconds before next polling iteration
            await asyncio.sleep(15)
        except Exception as e:
            logger.error("Error in scheduler loop: %s", e)
            await asyncio.sleep(15)

if __name__ == "__main__":
    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        logger.info("YouTube Scheduler stopped by user.")
