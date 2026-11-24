#!/usr/bin/env python3
"""
Dedicated YouTube Upload & Publishing Worker (Worker 3) for SupoClip.

2-2-2 PEAK VIRALITY SLOT SCHEDULE (Optimized for US & Canada Audience):
- Slot 1 (Early Morning): 05:30 - 07:00 EST -> 2 videos
- Slot 2 (Midday / Lunch): 13:00 - 14:30 EST -> 2 videos
- Slot 3 (Dual-Coast Prime Night): 22:00 - 23:30 EST -> 2 videos
Total: 6 videos per day.

Selection Rule:
- Strictly queries unuploaded clips ordered by virality_score DESC.
- Pre-flight validation gate ensures only verified high-quality clips are published.
- Interleaves streamers when candidates are close in score to maximize viewer retention.
- Spaces the 2 videos within each slot ~35 minutes apart to avoid cannibalization.
"""

import sys
import os
import time
import random
import asyncio
import logging
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta, time as dtime
from typing import Optional, Dict, Any, List, Tuple

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
from src.utils.upload_preflight_checklist import run_preflight, log_checklist_results, APPROVED_STREAMERS, BLOCKED_STREAMERS
from src.services.youtube_performance_tracker import YouTubePerformanceTracker
from src.services.system_audit_watchdog import SystemAuditWatchdog

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

# Timezone for audience optimization (US East / North America)
EST_TZ = ZoneInfo("America/New_York")

# The 3 Peak Slots (2 videos each = 6 videos/day)
UPLOAD_SLOTS = [
    {
        "id": "slot_1",
        "name": "Slot 1 (Early Morning)",
        "start": dtime(5, 30),
        "end": dtime(7, 0),
        "target_count": 2,
    },
    {
        "id": "slot_2",
        "name": "Slot 2 (Midday / Lunch)",
        "start": dtime(13, 0),
        "end": dtime(14, 30),
        "target_count": 2,
    },
    {
        "id": "slot_3",
        "name": "Slot 3 (Dual-Coast Prime Night)",
        "start": dtime(22, 0),
        "end": dtime(23, 30),
        "target_count": 2,
    },
]

# Spacing between the 2 uploads inside a single 90-minute slot
SLOT_INTRA_GAP_SECONDS = 35 * 60  # 35 minutes


class YouTubeUploadWorker:
    def __init__(self):
        self.engine = create_async_engine(DB_URL)
        self.uploader = HeadlessYouTubeUploader(headless=True)
        self.last_upload_time = 0.0
        self.last_audit_time = 0.0
        self.last_compliance_audit_time = 0.0
        self.compliance_audit_interval = 3 * 3600  # 3 hours
        self.last_uploaded_streamer: Optional[str] = None
        self.daily_limit_active_until = 0.0

    def get_current_slot(self) -> Optional[Dict[str, Any]]:
        """Returns the currently active slot definition if now_est falls inside it."""
        now_est = datetime.now(EST_TZ)
        for s in UPLOAD_SLOTS:
            start_dt = datetime.combine(now_est.date(), s["start"], tzinfo=EST_TZ)
            end_dt = datetime.combine(now_est.date(), s["end"], tzinfo=EST_TZ)
            if start_dt <= now_est <= end_dt:
                return {
                    **s,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "date": now_est.date(),
                }
        return None

    def get_next_slot(self) -> Tuple[datetime, Dict[str, Any]]:
        """Finds the next upcoming upload slot starting time and definition."""
        now_est = datetime.now(EST_TZ)
        upcoming = []
        for s in UPLOAD_SLOTS:
            start_dt = datetime.combine(now_est.date(), s["start"], tzinfo=EST_TZ)
            if start_dt > now_est:
                upcoming.append((start_dt, s))
        if not upcoming:
            tomorrow = now_est.date() + timedelta(days=1)
            start_dt = datetime.combine(tomorrow, UPLOAD_SLOTS[0]["start"], tzinfo=EST_TZ)
            upcoming.append((start_dt, UPLOAD_SLOTS[0]))
        return upcoming[0]

    async def get_slot_upload_history(self, slot_start_dt: datetime, slot_end_dt: datetime) -> List[Dict[str, Any]]:
        """Queries database for clips published during this slot window."""
        start_utc = slot_start_dt.astimezone(timezone.utc)
        end_utc = slot_end_dt.astimezone(timezone.utc)
        async with self.engine.connect() as conn:
            res = await conn.execute(
                text("""
                    SELECT id, hook_title, virality_score, workflow_meta,
                           COALESCE(
                               (workflow_meta->>'published_at')::timestamptz,
                               (workflow_meta->>'last_upload_attempt_at')::timestamptz,
                               created_at
                           ) as uploaded_at
                    FROM generated_clips
                    WHERE workflow_meta->>'uploaded' = 'true'
                      AND (
                          (workflow_meta->>'published_at')::timestamptz BETWEEN :start_utc AND :end_utc
                          OR (workflow_meta->>'last_upload_attempt_at')::timestamptz BETWEEN :start_utc AND :end_utc
                      )
                    ORDER BY uploaded_at ASC;
                """),
                {"start_utc": start_utc, "end_utc": end_utc}
            )
            rows = res.fetchall()
            return [
                {
                    "id": r[0],
                    "title": r[1],
                    "virality_score": r[2],
                    "workflow_meta": r[3] or {},
                    "uploaded_at": r[4],
                }
                for r in rows
            ]

    async def get_top_candidate_clip(self) -> Optional[Dict[str, Any]]:
        """
        Queries for the highest-scoring unuploaded clip in the database.
        Strictly orders by virality_score DESC.
        Filters out missing files, blocked streamers, or preflight-blocked clips.
        Applies alternating streamer interleaving if an alternate approved streamer
        is within 5 points of the top score.
        """
        import json

        async with self.engine.connect() as conn:
            res = await conn.execute(
                text("""
                    SELECT id, filename, file_path, virality_score, hook_title, workflow_meta, text, reasoning
                    FROM generated_clips
                    WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false')
                      AND (workflow_meta->>'preflight_blocked' IS NULL OR workflow_meta->>'preflight_blocked' != 'true')
                    ORDER BY virality_score DESC NULLS LAST, created_at DESC
                    LIMIT 30;
                """)
            )
            rows = res.fetchall()
            if not rows:
                return None

            valid_candidates = []
            for row in rows:
                wf = row[5] or {}
                if isinstance(wf, str):
                    try:
                        wf = json.loads(wf)
                    except Exception:
                        wf = {}
                streamer = (wf.get("streamer") or "unknown").lower().strip()
                if streamer in BLOCKED_STREAMERS:
                    continue
                if streamer not in APPROVED_STREAMERS:
                    continue

                raw_path = row[2]
                if not raw_path:
                    continue
                fp = Path(raw_path)
                if not fp.is_absolute():
                    fp = BACKEND_DIR / fp
                if not fp.exists():
                    continue

                valid_candidates.append({
                    "id": row[0],
                    "filename": row[1],
                    "file_path": fp,
                    "virality_score": row[3] or 0,
                    "title": row[4],
                    "workflow_meta": wf,
                    "text": row[6] or "",
                    "reasoning": row[7] or "",
                    "streamer": streamer,
                })

            if not valid_candidates:
                return None

            # Streamer interleaving: if top score is Asmon, and we just uploaded Asmon,
            # but there's a CaseOh or Speed clip within 5 points, alternate!
            top_score = valid_candidates[0]["virality_score"]
            if self.last_uploaded_streamer:
                alt = [
                    c for c in valid_candidates
                    if c["streamer"] != self.last_uploaded_streamer and c["virality_score"] >= top_score - 5
                ]
                if alt:
                    chosen = alt[0]
                    logger.info(
                        "🔀 Alternating Interleave: Selected %s [%d score] '%s' (after %s)",
                        chosen["streamer"],
                        chosen["virality_score"],
                        chosen["title"],
                        self.last_uploaded_streamer,
                    )
                    return chosen

            return valid_candidates[0]

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
                logger.info("Successfully published %d draft to Public!", len(results))
                for r in results:
                    logger.info("  Live Video: %s -> %s", r.get("title"), r.get("url"))
            return len(results)
        except Exception as e:
            logger.error("Error during draft publishing: %s", e)
            return 0

    async def upload_clip(self, clip: Dict[str, Any], slot_id: Optional[str] = None) -> bool:
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
            "🚀 Starting upload for [%s score] '%s' (Streamer: %s, Slot: %s)...",
            clip["virality_score"],
            title,
            streamer_name,
            slot_id,
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

        # 3. Generate or retrieve viral thumbnail
        thumb_path = None
        if clip.get("workflow_meta", {}).get("thumbnail_path"):
            candidate_th = Path(clip["workflow_meta"]["thumbnail_path"])
            if candidate_th.exists():
                thumb_path = candidate_th

        if not thumb_path:
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
                        "upload_slot": slot_id,
                    },
                )
                self.last_upload_time = time.time()
                streamer = clip.get("streamer") or clip.get("workflow_meta", {}).get("streamer")
                if streamer:
                    self.last_uploaded_streamer = streamer.lower()
                    logger.info("Updated last uploaded streamer: %s", self.last_uploaded_streamer)

                # Automatically prune local video & thumbnail files once verified Public
                try:
                    if file_path.exists():
                        file_path.unlink(missing_ok=True)
                    if thumb_path and Path(thumb_path).exists():
                        Path(thumb_path).unlink(missing_ok=True)
                    logger.info("🗑️ Pruned local files for published clip '%s'.", title[:30])
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
        Main autonomous execution loop enforcing 2-2-2 Slot Upload Policy.
        Slot 1: 05:30 - 07:00 EST (Early Morning) -> 2 videos
        Slot 2: 13:00 - 14:30 EST (Midday / Lunch) -> 2 videos
        Slot 3: 22:00 - 23:30 EST (Prime Night)    -> 2 videos
        Total: 6 videos / day, strictly selecting top virality score clips.
        """
        logger.info("🎯 YouTube 2-2-2 Slot Upload Worker STARTED.")
        logger.info("📅 Active Schedule (EST / America/New_York):")
        for s in UPLOAD_SLOTS:
            logger.info("   • %s: %s - %s EST (Target: %d videos)", s["name"], s["start"].strftime("%H:%M"), s["end"].strftime("%H:%M"), s["target_count"])
        logger.info("⏱️ Intra-slot spacing: %d minutes between videos in the same slot.", SLOT_INTRA_GAP_SECONDS // 60)
        logger.info("⭐ Clip selection: Strictly top virality score (virality_score DESC) with fair-share streamer interleaving.")

        while True:
            try:
                now_ts = time.time()
                now_est = datetime.now(EST_TZ)

                # 1. Automated 3-Hour System Master Checklist Audit
                if now_ts - self.last_compliance_audit_time >= self.compliance_audit_interval:
                    try:
                        logger.info("🛡️ Triggering Scheduled 3-Hour Master Checklist Compliance Audit...")
                        await SystemAuditWatchdog.run_full_system_audit()
                        self.last_compliance_audit_time = now_ts
                    except Exception as comp_err:
                        logger.error("System compliance audit notice: %s", comp_err)

                # 2. Periodic closed-loop performance audit (every 6 hours)
                if now_ts - self.last_audit_time >= 6 * 3600:
                    try:
                        await YouTubePerformanceTracker.run_audit_cycle()
                        self.last_audit_time = now_ts
                    except Exception as audit_err:
                        logger.warning("Closed-loop audit cycle warning: %s", audit_err)

                # Check if daily limit cooldown is active
                if now_ts < self.daily_limit_active_until:
                    sleep_rem = int(self.daily_limit_active_until - now_ts)
                    logger.info("🛑 Daily upload limit active. Sleeping %ds (~%.1f min)...", sleep_rem, sleep_rem / 60.0)
                    await asyncio.sleep(min(sleep_rem, 300))
                    continue

                # 3. Check Slot Status
                current_slot = self.get_current_slot()

                if current_slot is None:
                    next_start, next_slot = self.get_next_slot()
                    seconds_to_wait = (next_start - now_est).total_seconds()
                    mins_rem = int(seconds_to_wait // 60)
                    hours_rem = seconds_to_wait / 3600.0
                    logger.info(
                        "💤 [Outside Upload Windows]: Current time: %s EST. Next scheduled slot is %s at %s EST (~%d min / %.1f hrs).",
                        now_est.strftime("%H:%M:%S"),
                        next_slot["name"],
                        next_start.strftime("%H:%M"),
                        mins_rem,
                        hours_rem,
                    )
                    await asyncio.sleep(min(seconds_to_wait, 60))
                    continue

                # We are INSIDE an active slot!
                slot_uploads = await self.get_slot_upload_history(current_slot["start_dt"], current_slot["end_dt"])
                count = len(slot_uploads)
                target = current_slot["target_count"]

                if count >= target:
                    next_start, next_slot = self.get_next_slot()
                    seconds_to_wait = (next_start - now_est).total_seconds()
                    logger.info(
                        "✅ [%s Target Met]: All %d/%d scheduled videos uploaded for this slot! Next slot: %s at %s EST.",
                        current_slot["name"],
                        count,
                        target,
                        next_slot["name"],
                        next_start.strftime("%H:%M"),
                    )
                    await asyncio.sleep(min(seconds_to_wait, 60))
                    continue

                if count > 0:
                    # Check gap since previous upload in this slot
                    last_up = slot_uploads[-1]["uploaded_at"]
                    if last_up.tzinfo is None:
                        last_up = last_up.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc)
                    elapsed_seconds = (now_utc - last_up).total_seconds()
                    if elapsed_seconds < SLOT_INTRA_GAP_SECONDS:
                        rem_gap = int(SLOT_INTRA_GAP_SECONDS - elapsed_seconds)
                        logger.info(
                            "⏳ [%s Pacing]: Video %d/%d uploaded %d min ago. Waiting %d min gap before next upload (%d min remaining)...",
                            current_slot["name"],
                            count,
                            target,
                            int(elapsed_seconds // 60),
                            SLOT_INTRA_GAP_SECONDS // 60,
                            rem_gap // 60,
                        )
                        await asyncio.sleep(min(rem_gap, 60))
                        continue

                # Ready to upload for this slot!
                candidate = await self.get_top_candidate_clip()
                if not candidate:
                    logger.warning("⚠️ [%s]: No eligible unuploaded clips found in database! Retrying in 60s...", current_slot["name"])
                    await asyncio.sleep(60)
                    continue

                logger.info(
                    "🚀 [%s Upload %d/%d]: Launching upload for top virality clip [%d score] '%s' (Streamer: %s)...",
                    current_slot["name"],
                    count + 1,
                    target,
                    candidate["virality_score"],
                    candidate["title"],
                    candidate.get("streamer"),
                )

                success = await self.upload_clip(candidate, slot_id=current_slot["id"])
                if success:
                    self.last_upload_time = time.time()
                    logger.info(
                        "🎉 [%s Upload %d/%d SUCCESS]: '%s' is LIVE on YouTube!",
                        current_slot["name"],
                        count + 1,
                        target,
                        candidate["title"],
                    )
                else:
                    logger.error(
                        "❌ [%s Upload %d/%d FAILED]: Backing off 30s before retry.",
                        current_slot["name"],
                        count + 1,
                        target,
                    )
                    await asyncio.sleep(30)

            except Exception as loop_err:
                logger.error("Error in upload worker loop: %s", loop_err, exc_info=True)
                await asyncio.sleep(30)


if __name__ == "__main__":
    worker = YouTubeUploadWorker()
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
