#!/usr/bin/env python3
"""
Upload Pre-Flight Checklist Validator for SupoClip.

Implements every check from upload_checklist.md as executable Python code.
The upload worker calls `run_preflight(clip, description, thumb_path)` before
touching YouTube. If ANY check fails, the clip stays local.

Checklist sections:
  1. Video File Integrity
  2. Duration
  3. Title
  4. Description
  5. Thumbnail
  6. Allowed Streamers
  7-10. (Visibility, Timing, Duplicates, Metadata are enforced at upload time)
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("PreflightChecklist")

# ─── Section 6: Approved streamers (ONLY these are allowed) ───
APPROVED_STREAMERS = {"ishowspeed", "asmong", "kai"}
BLOCKED_STREAMERS = {"botez", "xqc", "jynxzi", "adinross"}


class CheckResult:
    """One pass/fail result from a single checklist item."""
    def __init__(self, section: str, check: str, passed: bool, detail: str = ""):
        self.section = section
        self.check = check
        self.passed = passed
        self.detail = detail

    def __repr__(self):
        status = "✅" if self.passed else "❌"
        return f"{status} [{self.section}] {self.check}: {self.detail}"


def _probe_video(file_path: Path) -> Optional[Dict]:
    """Run ffprobe and return parsed JSON, or None on failure."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        logger.warning("ffprobe failed for %s: %s", file_path, e)
    return None


def run_preflight(
    clip: Dict[str, Any],
    description: str,
    thumb_path: Optional[Path],
    file_path: Path,
) -> Tuple[bool, List[CheckResult]]:
    """
    Runs the full pre-flight checklist against a clip BEFORE it touches YouTube.

    Returns:
        (all_passed: bool, results: list of CheckResult)
    """
    results: List[CheckResult] = []

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 1: Video File Integrity
    # ═══════════════════════════════════════════════════════════════════

    # 1a. File exists
    file_exists = file_path.exists()
    results.append(CheckResult("File Integrity", "File exists on disk", file_exists,
                               str(file_path) if file_exists else f"MISSING: {file_path}"))
    if not file_exists:
        # Can't run remaining checks without the file
        return False, results

    # 1b. File is not empty
    file_size = file_path.stat().st_size
    not_empty = file_size > 0
    results.append(CheckResult("File Integrity", "File is not empty", not_empty,
                               f"{file_size:,} bytes"))

    # 1c & 1d. Has video stream + Has audio stream + duration
    probe = _probe_video(file_path)
    has_video = False
    has_audio = False
    duration = 0.0

    if probe:
        streams = probe.get("streams", [])
        for s in streams:
            if s.get("codec_type") == "video":
                has_video = True
            if s.get("codec_type") == "audio":
                has_audio = True
        fmt = probe.get("format", {})
        try:
            duration = float(fmt.get("duration", 0))
        except (ValueError, TypeError):
            duration = 0.0
    else:
        results.append(CheckResult("File Integrity", "ffprobe readable", False,
                                   "ffprobe returned no data"))
        return False, results

    results.append(CheckResult("File Integrity", "Has video stream", has_video,
                               "video track found" if has_video else "NO VIDEO TRACK"))
    results.append(CheckResult("File Integrity", "Has audio stream", has_audio,
                               "audio track found" if has_audio else "NO AUDIO TRACK — zero-audio clips must never upload"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 2: Duration
    # ═══════════════════════════════════════════════════════════════════

    min_ok = duration >= 30.0
    results.append(CheckResult("Duration", "Minimum 30 seconds", min_ok,
                               f"{duration:.1f}s" + ("" if min_ok else " — TOO SHORT, rejected")))

    context_ok = 30.0 <= duration <= 58.0
    results.append(CheckResult("Duration", "Context-appropriate length (30–58s)", context_ok,
                               f"{duration:.1f}s" + ("" if context_ok else " — outside preferred range (soft warning)")))
    # Duration 30-58 is a soft check; the hard gate is 30-60.

    shorts_ok = duration < 60.0
    results.append(CheckResult("Duration", "Under 60 seconds (Shorts limit)", shorts_ok,
                               f"{duration:.1f}s" + ("" if shorts_ok else " — EXCEEDS 60s, cannot be a Short")))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 3: Title
    # ═══════════════════════════════════════════════════════════════════

    title = clip.get("title") or ""

    title_not_empty = len(title.strip()) > 0
    results.append(CheckResult("Title", "Title is not empty", title_not_empty,
                               f"'{title[:50]}'" if title_not_empty else "EMPTY TITLE"))

    ends_shorts = title.strip().endswith("#shorts")
    results.append(CheckResult("Title", "Ends with #shorts", ends_shorts,
                               "yes" if ends_shorts else "missing #shorts suffix"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 4: Description
    # ═══════════════════════════════════════════════════════════════════

    desc_not_empty = len(description.strip()) > 50
    results.append(CheckResult("Description", "Description is not empty (>50 chars)", desc_not_empty,
                               f"{len(description)} chars" if desc_not_empty else f"ONLY {len(description)} chars — too short"))

    has_attribution = "🎮 Featured Streamer:" in description
    results.append(CheckResult("Description", "Contains streamer attribution", has_attribution,
                               "found" if has_attribution else "MISSING '🎮 Featured Streamer:' line"))

    has_stream_link = "📺 Watch original stream:" in description
    results.append(CheckResult("Description", "Contains original stream link", has_stream_link,
                               "found" if has_stream_link else "MISSING '📺 Watch original stream:' line"))

    has_fair_use = "Section 107" in description or "Copyright Disclaimer" in description
    results.append(CheckResult("Description", "Contains fair use disclaimer", has_fair_use,
                               "found" if has_fair_use else "MISSING Section 107 / Copyright Disclaimer"))

    has_hashtags = "#shorts" in description
    results.append(CheckResult("Description", "Contains hashtags", has_hashtags,
                               "found" if has_hashtags else "MISSING #shorts hashtag"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 5: Thumbnail
    # ═══════════════════════════════════════════════════════════════════

    thumb_generated = thumb_path is not None and Path(thumb_path).exists()
    results.append(CheckResult("Thumbnail", "Thumbnail was generated", thumb_generated,
                               str(thumb_path) if thumb_generated else "NO THUMBNAIL FILE"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 6: Allowed Streamers
    # ═══════════════════════════════════════════════════════════════════

    streamer = (clip.get("workflow_meta") or {}).get("streamer", "").lower().strip()
    streamer_approved = streamer in APPROVED_STREAMERS
    streamer_blocked = streamer in BLOCKED_STREAMERS

    if streamer_blocked:
        results.append(CheckResult("Allowed Streamers", "Streamer is on the approved list", False,
                                   f"BLOCKED: '{streamer}' is explicitly removed — do not upload"))
    elif streamer_approved:
        results.append(CheckResult("Allowed Streamers", "Streamer is on the approved list", True,
                                   f"'{streamer}' ✓"))
    else:
        results.append(CheckResult("Allowed Streamers", "Streamer is on the approved list", False,
                                   f"UNKNOWN: '{streamer}' is not in the approved list ({', '.join(sorted(APPROVED_STREAMERS))})"))

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 9 (partial): DB cross-check
    # ═══════════════════════════════════════════════════════════════════

    meta = clip.get("workflow_meta") or {}
    already_uploaded = str(meta.get("uploaded", "")).lower() == "true"
    results.append(CheckResult("No Duplicates", "DB workflow_meta.uploaded is not true", not already_uploaded,
                               "not uploaded yet" if not already_uploaded else "ALREADY MARKED UPLOADED — skip"))

    # ═══════════════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════════════

    # Hard-fail checks (soft warning for 30-58s range is non-blocking)
    hard_fail_checks = [r for r in results if not r.passed and "Context-appropriate" not in r.check]
    all_passed = len(hard_fail_checks) == 0

    return all_passed, results


def log_checklist_results(results: List[CheckResult], clip_title: str) -> None:
    """Logs every checklist result for audit trail."""
    logger.info("┌─── PRE-FLIGHT CHECKLIST for '%s' ───", clip_title[:40])
    for r in results:
        logger.info("│ %s", r)
    passed = all(r.passed or "Context-appropriate" in r.check for r in results)
    if passed:
        logger.info("└─── ✅ ALL CHECKS PASSED — cleared for upload ───")
    else:
        failed = [r for r in results if not r.passed and "Context-appropriate" not in r.check]
        logger.error("└─── ❌ %d CHECK(S) FAILED — clip stays LOCAL ───", len(failed))
        for f in failed:
            logger.error("    BLOCKED BY: %s", f)
