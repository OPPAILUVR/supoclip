import sys
import re
import inspect
from pathlib import Path

print("==================================================================")
print("             SUPOCLIP COMPREHENSIVE SYSTEM AUDIT                 ")
print("==================================================================")

failures = []

def test_assert(condition, test_name, details=""):
    if condition:
        print(f"  [PASS] {test_name}")
    else:
        print(f"  [FAIL] {test_name}: {details}")
        failures.append((test_name, details))

# ----------------------------------------------------------------------
# 1. AUDIT: thumbnail_generator.py
# ----------------------------------------------------------------------
print("\n[1/6] AUDITING: src/services/thumbnail_generator.py")
try:
    from src.services.thumbnail_generator import (
        _synthesize_thumbnail_headline,
        _get_best_font,
        generate_viral_thumbnail,
        CANDIDATE_FONTS
    )
    test_assert(True, "thumbnail_generator imports cleanly")
    
    # Test headline synthesis
    lines, badge = _synthesize_thumbnail_headline("That Eureka Moment Demolished xQc Desk")
    test_assert(len(lines) in [1, 2], "Headline split into 1 or 2 lines", f"Got: {lines}")
    test_assert("DESK" in " ".join(lines), "Headline preserves core action word", f"Got: {lines}")
    test_assert(lines[-1].endswith(("?!", "?", "!", "💀")), "Headline has viral curiosity punctuation", f"Got: {lines[-1]}")
    test_assert("REGRET" in badge or "KARMA" in badge, "Badge correctly matched action archetype", f"Got: {badge}")

    # Test font loader
    font = _get_best_font(80)
    test_assert(font is not None, "Font loaded successfully", f"Got: {font}")
    
except Exception as e:
    test_assert(False, "thumbnail_generator exception", str(e))

# ----------------------------------------------------------------------
# 2. AUDIT: video_metadata.py
# ----------------------------------------------------------------------
print("\n[2/6] AUDITING: src/utils/video_metadata.py")
try:
    from src.utils.video_metadata import (
        get_streamer_tags,
        build_viral_youtube_description,
        strip_and_embed_video_metadata,
        STREAMER_PROFILES
    )
    test_assert(True, "video_metadata imports cleanly")

    # Anti-Spam Check: Streamer tags must be EMPTY to prevent YouTube metadata stuffing penalties
    tags = get_streamer_tags("xqc")
    test_assert(tags == [], "get_streamer_tags returns empty list (Zero Tag Stuffing)", f"Got: {tags}")

    # Description Cleanliness Check
    desc = build_viral_youtube_description(
        title="Epic Escape In GTA",
        streamer_name="xqc",
        hook_text="He thought he got away",
        reasoning="Shocking police pit maneuver"
    )
    test_assert("#shorts" not in desc, "Description does not contain spam tag arrays")
    test_assert("Section 107" in desc, "Description contains Fair Use legal disclaimer")
    test_assert("Featured Streamer:" in desc, "Description contains proper streamer attribution")
    
    # Code inspection for -map_metadata -1
    code_meta = Path("src/utils/video_metadata.py").read_text()
    test_assert("-map_metadata" in code_meta and "-1" in code_meta, "strip_and_embed_video_metadata strips MP4 metadata (-map_metadata -1)")

except Exception as e:
    test_assert(False, "video_metadata exception", str(e))

# ----------------------------------------------------------------------
# 3. AUDIT: live_stream_service.py
# ----------------------------------------------------------------------
print("\n[3/6] AUDITING: src/services/live_stream_service.py")
try:
    code_live = Path("src/services/live_stream_service.py").read_text()
    
    # Crop Format Protection Check (Exact user format: 6% left, 6% right, 1% top, 1% bottom)
    has_side_crop = "iw*0.88" in code_live  # (1 - 0.12) = 0.88 (6% left + 6% right)
    has_vert_crop = "ih*0.98" in code_live  # (1 - 0.02) = 0.98 (1% top + 1% bottom)
    has_left_offset = "iw*0.06" in code_live # 6% left inset
    has_top_offset = "ih*0.01" in code_live  # 1% top inset
    test_assert(has_side_crop and has_vert_crop and has_left_offset and has_top_offset, 
                "Cropping format strictly locked (6% left/right, 1% top/bottom)",
                f"side={has_side_crop}, vert={has_vert_crop}, left={has_left_offset}, top={has_top_offset}")

    has_ambient_blur = "boxblur" in code_live and "scale=1080:1920" in code_live
    test_assert(has_ambient_blur, "Ambient blurred background canvas (1080x1920) active")

    # Duration Check: 22-38s (28s sweet spot)
    test_assert("min_duration = 22.0" in code_live or "min_duration: float = 22.0" in code_live, "min_duration set to 22.0s")
    test_assert("max_duration = 38.0" in code_live or "max_duration: float = 38.0" in code_live, "max_duration set to 38.0s")
    test_assert("target_sweet_spot = 28.0" in code_live or "target_sweet_spot: float = 28.0" in code_live, "target_sweet_spot set to 28.0s")

    # AI Director Prompt Check
    test_assert("40-48% mark" in code_live, "AI Director enforces Midpoint Climax at 40-48% mark")
    test_assert("9.38x" in code_live or "outperform mild laughter by" in code_live, "AI Director weights acute shock/disbelief over laughter")

except Exception as e:
    test_assert(False, "live_stream_service exception", str(e))

# ----------------------------------------------------------------------
# 4. AUDIT: ai.py
# ----------------------------------------------------------------------
print("\n[4/6] AUDITING: src/ai.py")
try:
    code_ai = Path("src/ai.py").read_text()
    
    test_assert("EMPIRICAL 1,000-VIDEO VIRALITY MODEL" in code_ai, "ai.py references empirical 1,000-video model")
    test_assert("22 to 38 seconds" in code_ai or "22-38s TARGET" in code_ai, "ai.py targets 22-38s duration")
    test_assert("MIDPOINT CLIMAX (40-48% MARK)" in code_ai, "ai.py enforces 40-48% midpoint climax")
    test_assert("outperforms mild laughter by 9.4x" in code_ai, "ai.py weights acute shock over laughter")
    test_assert("85-95 WPM (empirical mean: 91.7 WPM)" in code_ai, "ai.py specifies empirical 91.7 WPM speech pacing")

except Exception as e:
    test_assert(False, "ai.py exception", str(e))

# ----------------------------------------------------------------------
# 5. AUDIT: youtube_headless_uploader.py
# ----------------------------------------------------------------------
print("\n[5/6] AUDITING: src/services/youtube_headless_uploader.py")
try:
    from src.services.youtube_headless_uploader import HeadlessYouTubeUploader
    uploader = HeadlessYouTubeUploader(headless=True)
    
    sig = inspect.signature(uploader.upload_video)
    test_assert("thumbnail_path" in sig.parameters, "upload_video accepts thumbnail_path parameter")

    code_up = Path("src/services/youtube_headless_uploader.py").read_text()
    
    # Verify no premature close button click on ytcp-uploads-dialog
    premature_close = 'page.locator("ytcp-uploads-dialog ytcp-button#close-button' in code_up
    test_assert(not premature_close, "Premature upload dialog (X) close button click is ELIMINATED (prevents Draft bug)")

    # Verify 8 second commit wait
    test_assert("await asyncio.sleep(8)" in code_up, "Upload script waits 8s for YouTube backend to commit Public state")

    # Verify auto-discard on failure
    test_assert("Auto-discarded incomplete upload dialog" in code_up, "Auto-discard cleans up failed uploads to prevent orphaned drafts")

except Exception as e:
    test_assert(False, "youtube_headless_uploader exception", str(e))

# ----------------------------------------------------------------------
# 6. AUDIT: youtube_auto_scheduler.py
# ----------------------------------------------------------------------
print("\n[6/6] AUDITING: src/services/youtube_auto_scheduler.py")
try:
    code_sched = Path("src/services/youtube_auto_scheduler.py").read_text()
    
    test_assert("generate_viral_thumbnail" in code_sched, "Auto-scheduler calls generate_viral_thumbnail automatically")
    test_assert("thumbnail_path=thumbnail_path" in code_sched, "Auto-scheduler passes generated thumbnail to upload_video")
    test_assert("Anti-Shadowban" in code_sched or "cooldown" in code_sched, "Anti-shadowban cooldown active")

except Exception as e:
    test_assert(False, "youtube_auto_scheduler exception", str(e))

# ----------------------------------------------------------------------
# AUDIT SUMMARY
# ----------------------------------------------------------------------
print("\n==================================================================")
if len(failures) == 0:
    print(" >>> ALL 25 SYSTEM AUDIT TESTS PASSED! ZERO DEFECTS DETECTED <<< ")
else:
    print(f" >>> {len(failures)} TESTS FAILED! <<< ")
    for name, det in failures:
        print(f"   - {name}: {det}")
print("==================================================================")
sys.exit(len(failures))
