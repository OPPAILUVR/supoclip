#!/usr/bin/env python3
"""
Dedicated YouTube Upload & Publishing Worker (Worker 3) for SupoClip.
STRICT SCHEDULE RULES:
1. Videos with virality score >= 95: Uploaded INSTANTLY with a 3-4 minute (180-240s) gap.
2. Videos with virality score < 95: Uploaded RANDOMLY with a 50-100 minute (3000-6000s) gap.
"""

import sys
import os
import time
import random
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from src.services.youtube_headless_uploader import HeadlessYouTubeUploader
from src.utils.video_metadata import (
    strip_and_embed_video_metadata,
    get_streamer_tags,
    build_viral_youtube_description,
)
from src.services.thumbnail_generator import generate_viral_thumbnail
from src.utils.upload_preflight_checklist import run_preflight, log_checklist_results
from src.services.youtube_performance_tracker import YouTubePerformanceTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [YouTubeUploadWorker]: %(message)s",
    handlers=[
        logging.FileHandler(str(BACKEND_DIR / "youtube_upload_worker.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("YouTubeUploadWorker")

DB_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://luv@localhost:5432/supoclip")

# Timing rules as strictly instructed
INSTANT_MIN_COOLDOWN = 180         # 3 minutes for 95+
INSTANT_MAX_COOLDOWN = 240         # 4 minutes for 95+
REGULAR_MIN_COOLDOWN = 50 * 60     # 50 minutes for <95
REGULAR_MAX_COOLDOWN = 100 * 60    # 100 minutes for <95


class YouTubeUploadWorker:
    def __init__(self):
        self.engine = create_async_engine(DB_URL)
        self.uploader = HeadlessYouTubeUploader(headless=True)
        self.last_upload_time = 0.0
        self.last_audit_time = 0.0
        self.daily_limit_active_until = 0.0
        self.current_instant_cooldown = random.randint(INSTANT_MIN_COOLDOWN, INSTANT_MAX_COOLDOWN)
        self.next_regular_scheduled_time = time.time() + random.randint(REGULAR_MIN_COOLDOWN, REGULAR_MAX_COOLDOWN)

    async def get_next_95_plus_clip(self) -> Optional[Dict[str, Any]]:
        """Queries for the highest-scoring unuploaded clip with virality >= 95."""
        async with self.engine.connect() as conn:
            res = await conn.execute(
                text("""
                    SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
                    FROM generated_clips
                    WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false')
                      AND virality_score >= 95
                    ORDER BY virality_score DESC, created_at DESC
                    LIMIT 1;
                """)
            )
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
                    "is_instant": True,
                }
        return None

    async def get_next_regular_clip(self) -> Optional[Dict[str, Any]]:
        """Queries for the highest-scoring unuploaded clip with virality < 95."""
        async with self.engine.connect() as conn:
            res = await conn.execute(
                text("""
                    SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
                    FROM generated_clips
                    WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false')
                      AND virality_score < 95
                    ORDER BY virality_score DESC, created_at DESC
                    LIMIT 1;
                """)
            )
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
                    "is_instant": False,
                }
        return None

    async def mark_clip_status(self, clip_id: str, uploaded: bool, meta: Dict[str, Any]) -> None:
        """Updates PostgreSQL clip workflow metadata."""
        import json
        meta_update = {
            "uploaded": uploaded,
            "last_upload_attempt_at": datetime.now(timezone.utc).isoformat(),
            **meta,
        }
        async with self.engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE generated_clips
                    SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:update_meta AS jsonb)
                    WHERE id = :id;
                """),
                {"id": clip_id, "update_meta": json.dumps(meta_update)},
            )

    async def rescue_and_publish_drafts(self, max_batch: int = 1) -> int:
        """Publishes existing drafts on YouTube Studio if new uploads hit rate limits."""
        logger.info("Checking YouTube Studio for existing unique drafts...")
        try:
            results = await self.uploader.publish_all_unique_drafts(max_count=max_batch)
            if results:
                self.last_upload_time = time.time()
                self.current_instant_cooldown = random.randint(INSTANT_MIN_COOLDOWN, INSTANT_MAX_COOLDOWN)
                logger.info("Successfully published %d draft to Public! Next action in %ds (~%.1f min).", len(results), self.current_instant_cooldown, self.current_instant_cooldown / 60.0)
                for r in results:
                    logger.info("  Live Video: %s -> %s", r.get("title"), r.get("url"))
            return len(results)
        except Exception as e:
            logger.error("Error during draft publishing: %s", e)
            return 0

    async def upload_clip(self, clip: Dict[str, Any]) -> bool:
        """Executes full upload for a single clip with thumbnail & metadata."""
        clip_id = clip["id"]
        file_path = clip["file_path"]
        if not file_path.is_absolute():
            file_path = BACKEND_DIR / file_path

        if not file_path.exists():
            logger.error("Clip file not found on disk: %s", file_path)
            await self.mark_clip_status(clip_id, False, {"error": "file_not_found"})
            return False

        streamer_name = clip.get("workflow_meta", {}).get("streamer") or "Streamer"
        title = clip.get("title") or f"{streamer_name} Viral Stream Moment"
        if not title.endswith("#shorts"):
            title = f"{title} #shorts"

        logger.info(
            "🚀 Starting upload for [%s score] '%s' (Streamer: %s)...",
            clip["virality_score"],
            title,
            streamer_name,
        )

        # 1. Clean metadata
        tags = get_streamer_tags(streamer_name)
        try:
            strip_and_embed_video_metadata(
                video_path=file_path,
                title=title,
                streamer_name=streamer_name,
                custom_tags=tags,
                description=None,
            )
        except Exception as meta_err:
            logger.warning("Metadata embedding notice: %s", meta_err)

        # 2. Build high-CTR description
        description = build_viral_youtube_description(
            title=title,
            streamer_name=streamer_name,
            hook_text=clip.get("text", ""),
            reasoning=clip.get("reasoning", ""),
        )

        # 3. Generate viral thumbnail
        thumb_path = None
        try:
            thumb_path = generate_viral_thumbnail(
                video_path=file_path,
                hook_title=title,
                streamer_name=streamer_name,
            )
            logger.info("Generated high-CTR viral thumbnail: %s", thumb_path.name)
        except Exception as th_err:
            logger.warning("Thumbnail notice (non-fatal): %s", th_err)

        # ═══════════════════════════════════════════════════════════════
        # PRE-FLIGHT CHECKLIST GATE — clip stays LOCAL if any check fails
        # ═══════════════════════════════════════════════════════════════
        preflight_clip = {
            "title": title,
            "workflow_meta": clip.get("workflow_meta", {}),
            "text": clip.get("text", ""),
            "reasoning": clip.get("reasoning", ""),
            "virality_score": clip.get("virality_score", 0),
        }
        passed, results = run_preflight(
            clip=preflight_clip,
            description=description,
            thumb_path=thumb_path,
            file_path=file_path,
        )
        log_checklist_results(results, title)

        if not passed:
            failed_checks = [r for r in results if not r.passed and "Context-appropriate" not in r.check]
            fail_reasons = "; ".join(f"{r.check}: {r.detail}" for r in failed_checks)
            logger.error("🚫 PRE-FLIGHT FAILED for '%s'. Clip stays LOCAL. Reasons: %s", title, fail_reasons)
            await self.mark_clip_status(clip_id, False, {
                "error": f"preflight_failed: {fail_reasons}",
                "preflight_blocked": True,
            })
            return False

        # 4. Upload headlessly via Playwright
        try:
            res = await self.uploader.upload_video(
                video_path=file_path,
                title=title,
                description=description,
                tags=tags,
                is_short=True,
                thumbnail_path=thumb_path,
            )

            # STRICT VERIFICATION: Video MUST be confirmed published to Public with a valid URL
            is_success = bool(
                res.get("success") and
                (res.get("status") == "published" or res.get("verified")) and
                res.get("video_url")
            )
            if is_success:
                video_url = res.get("video_url")
                logger.info("✅ Upload & Publish SUCCESS: '%s' is 100%% LIVE on YouTube! (URL: %s)", title, video_url)
                await self.mark_clip_status(
                    clip_id,
                    True,
                    {
                        "youtube_title": title,
                        "youtube_url": video_url,
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "verified_public": True,
                    },
                )
                self.last_upload_time = time.time()

                # Automatically prune local video & thumbnail files once 100% verified Public on YouTube
                try:
                    if file_path.exists():
                        file_path.unlink(missing_ok=True)
                    if thumb_path and Path(thumb_path).exists():
                        Path(thumb_path).unlink(missing_ok=True)
                    logger.info("🗑️ Pruned local files for published clip '%s' (freed storage).", title[:30])
                except Exception as prune_err:
                    logger.debug("Notice pruning published clip files: %s", prune_err)

                return True
            else:
                err_msg = str(res.get("error", "upload_incomplete_or_not_public"))
                if "daily upload limit" in err_msg.lower():
                    logger.warning("🛑 YouTube daily upload limit reached. Backing off new uploads for 1 hour.")
                    self.daily_limit_active_until = time.time() + 3600
                await self.mark_clip_status(clip_id, False, {"error": err_msg})
                return False

        except PermissionError as pe:
            if "daily upload limit" in str(pe).lower():
                logger.warning("🛑 Daily upload limit hit: %s", pe)
                self.daily_limit_active_until = time.time() + 3600
            await self.mark_clip_status(clip_id, False, {"error": str(pe)})
            return False
        except Exception as e:
            logger.error("Upload error for '%s': %s", title, e)
            await self.mark_clip_status(clip_id, False, {"error": str(e)})
            return False

    async def run(self) -> None:
        """
        Main autonomous execution loop.
        - 95+ score clips: Uploaded ONE at a time with strict 3-4 minute gap.
        - < 95 score clips: Uploaded ONE at a time with 50-100 minute gap.
        - Local Storage Rule: Clips stay 100% on local computer until slot is ready.
        - Zero Drafts Rule: Videos are NEVER sent to drafts. Verified Public before completing.
        """
        logger.info("🎯 Dedicated YouTube Upload & Publishing Worker (Worker 3) STARTED.")
        logger.info("Cadence Rules Locked:")
        logger.info("  1. Virality >= 95: INSTANT with 3-4 min (%d-%ds) gap", INSTANT_MIN_COOLDOWN, INSTANT_MAX_COOLDOWN)
        logger.info("  2. Virality < 95: RANDOM 50-100 min (%d-%ds) gap", REGULAR_MIN_COOLDOWN, REGULAR_MAX_COOLDOWN)
        logger.info("  3. Zero Drafts Policy: Videos go directly to Public; drafts strictly prohibited.")

        while True:
            try:
                now = time.time()

                # Periodic closed-loop performance audit (every 6 hours)
                if now - self.last_audit_time >= 6 * 3600:
                    try:
                        await YouTubePerformanceTracker.run_audit_cycle()
                        self.last_audit_time = now
                    except Exception as audit_err:
                        logger.warning("Closed-loop audit cycle warning: %s", audit_err)

                # Check if daily limit cooldown is active
                if now < self.daily_limit_active_until:
                    sleep_rem = int(self.daily_limit_active_until - now)
                    logger.info("🛑 Daily upload limit active. Sleeping %ds (~%.1f min) until quota reset...", sleep_rem, sleep_rem / 60.0)
                    await asyncio.sleep(min(sleep_rem, 300))
                    continue

                # =====================================================================
                # TIER 1: Check for any 95+ VIRALITY SCORE clips (INSTANT 3-4 MIN GAP)
                # =====================================================================
                clip_95 = await self.get_next_95_plus_clip()
                if clip_95:
                    time_since_last = now - self.last_upload_time
                    if self.last_upload_time > 0 and time_since_last < self.current_instant_cooldown:
                        remaining = int(self.current_instant_cooldown - time_since_last)
                        logger.info(
                            "⏳ [95+ Score Priority]: Detected viral clip [%d score] '%s'. Cooling down 3-4 min gap (%ds remaining, ~%.1f min)...",
                            clip_95["virality_score"],
                            clip_95["title"],
                            remaining,
                            remaining / 60.0,
                        )
                        await asyncio.sleep(min(remaining, 15))
                        continue

                    # Cooldown satisfied -> Upload ONE 95+ clip immediately!
                    logger.info(
                        "⚡ [95+ INSTANT UPLOAD]: Uploading ultra-viral clip [%d score] '%s'...",
                        clip_95["virality_score"],
                        clip_95["title"],
                    )
                    success = await self.upload_clip(clip_95)
                    if success:
                        self.last_upload_time = time.time()
                        self.current_instant_cooldown = random.randint(INSTANT_MIN_COOLDOWN, INSTANT_MAX_COOLDOWN)
                        logger.info("✅ 95+ Clip is LIVE & PUBLIC! Next 95+ clip in %ds (3-4 min gap).", self.current_instant_cooldown)
                    else:
                        logger.warning("Upload attempt failed for '%s'. Backing off 30s before retry.", clip_95["title"])
                        await asyncio.sleep(30)
                    continue

                # =====================================================================
                # TIER 2: Regular clips (<95 score) with RANDOM 50-100 MINUTE GAP
                # =====================================================================
                if now >= self.next_regular_scheduled_time:
                    time_since_last = now - self.last_upload_time
                    if self.last_upload_time > 0 and time_since_last < INSTANT_MIN_COOLDOWN:
                        await asyncio.sleep(15)
                        continue

                    reg_clip = await self.get_next_regular_clip()
                    if reg_clip:
                        logger.info(
                            "📅 [50-100 MIN BATCH]: Uploading scheduled clip [%d score] '%s'...",
                            reg_clip["virality_score"],
                            reg_clip["title"],
                        )
                        success = await self.upload_clip(reg_clip)
                        if success:
                            self.last_upload_time = time.time()
                            gap_seconds = random.randint(REGULAR_MIN_COOLDOWN, REGULAR_MAX_COOLDOWN)
                            self.next_regular_scheduled_time = time.time() + gap_seconds
                            logger.info(
                                "✅ Scheduled clip is LIVE! Next regular upload scheduled in %d min (~%.1f hrs).",
                                gap_seconds // 60,
                                gap_seconds / 3600.0,
                            )
                    else:
                        gap_seconds = random.randint(REGULAR_MIN_COOLDOWN, REGULAR_MAX_COOLDOWN)
                        self.next_regular_scheduled_time = time.time() + gap_seconds
                else:
                    time_until_regular = int(self.next_regular_scheduled_time - now)
                    logger.info(
                        "💤 [Queue Idle]: No 95+ clips pending. Next regular (<95) upload in %d min (~%.1f hrs).",
                        time_until_regular // 60,
                        time_until_regular / 3600.0,
                    )
                    await asyncio.sleep(min(time_until_regular, 30))

            except Exception as loop_err:
                logger.error("Error in upload worker loop: %s", loop_err)
                await asyncio.sleep(30)


if __name__ == "__main__":
    worker = YouTubeUploadWorker()
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
