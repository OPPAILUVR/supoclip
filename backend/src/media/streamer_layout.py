"""Streamer Facecam + Gameplay / Content Separation Pipeline for Live Auto-Clipping.

Analyzes live stream broadcasts to detect stream layouts and separate the streamer's
camera from game/content into optimal 9:16 vertical short formats:

1. Side-by-Side Streams (e.g. Chess streams, screen-share + camera, co-streams):
   - Detects the vertical partition dividing content (e.g. chess board) from streamer.
   - Top Tile (~1040px): Full content (chess board / shared screen), complete & uncropped.
   - Bottom Tile (~880px): Streamer camera zoomed out to show upper body, desk, room, mic.
   - Subtitles placed cleanly in the middle divider (matching professional clippers).

2. Corner Facecam Streams (e.g. GTA, gaming streams):
   - Detects stationary corner webcam overlay.
   - Top Tile (760px): Streamer webcam zoomed out comfortably (full camera frame).
   - Bottom Tile (1160px): Game action shifted to avoid webcam overlap.
   - Subtitles placed at the bottom.

3. Fullscreen / Just Chatting / Single Camera:
   - Returns None so the caller renders a single 9:16 frame, preventing the video
     from duplicating across upper and lower frames.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .face_detection import open_yunet_detector
from .ffmpeg import clamp_even, round_to_even

logger = logging.getLogger(__name__)

OUT_W = 1080
OUT_H = 1920


def detect_streamer_layout(
    video_path: Path,
    width: int,
    height: int,
    max_samples: int = 16,
) -> Optional[Dict[str, Any]]:
    """Detect streamer layout and build the optimal [Content / Streamer] 9:16 layout.

    Returns dict with {'video_filter': str, 'mode': 'complex', 'caption_y': float}
    or None if the video is single-camera/fullscreen (no separation needed).
    """
    if width < 320 or height < 240:
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total_frames / fps if fps > 0 else 0.0

    if duration < 1.0:
        cap.release()
        return None

    detector = open_yunet_detector()
    if not detector:
        cap.release()
        return None

    sample_count = min(max_samples, max(6, int(duration * 2)))
    sample_times = np.linspace(0.4, max(0.4, duration - 0.4), sample_count)
    face_detections: List[Dict[str, Any]] = []
    frames_for_grad: List[np.ndarray] = []

    try:
        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            if len(frames_for_grad) < 4:
                frames_for_grad.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            boxes = detector.detect(frame)
            for b in boxes:
                # b: (x, y, w, h, score)
                if b[4] >= 0.65:
                    face_detections.append({"t": t, "box": b})
    finally:
        cap.release()

    if not face_detections:
        return None

    # Cluster detections by spatial proximity (distance < 120px)
    clusters: List[Dict[str, Any]] = []
    for d in face_detections:
        bx, by, bw, bh, score = d["box"]
        cx, cy = bx + bw / 2, by + bh / 2
        matched = False
        for c in clusters:
            if abs(cx - c["cx"]) < 120 and abs(cy - c["cy"]) < 120:
                c["boxes"].append(d["box"])
                c["cx"] = float(np.mean([b[0] + b[2] / 2 for b in c["boxes"]]))
                c["cy"] = float(np.mean([b[1] + b[3] / 2 for b in c["boxes"]]))
                matched = True
                break
        if not matched:
            clusters.append({"cx": cx, "cy": cy, "boxes": [d["box"]]})

    min_count = max(2, int(len(sample_times) * 0.20))
    stable_clusters = []
    for c in clusters:
        n = len(c["boxes"])
        if n < min_count:
            continue
        cx, cy = c["cx"], c["cy"]
        med_w = float(np.median([b[2] for b in c["boxes"]]))
        med_h = float(np.median([b[3] for b in c["boxes"]]))
        std_x = float(np.std([b[0] + b[2] / 2 for b in c["boxes"]]))
        std_y = float(np.std([b[1] + b[3] / 2 for b in c["boxes"]]))
        if std_x < 65 and std_y < 65:
            stable_clusters.append({
                "cx": cx, "cy": cy, "w": med_w, "h": med_h,
                "count": n, "std_x": std_x, "std_y": std_y,
                "h_frac": med_h / height, "w_frac": med_w / width,
                "cx_frac": cx / width, "cy_frac": cy / height,
            })

    if not stable_clusters:
        return None

    # Pick the most prominent/stationary cluster
    stable_clusters.sort(key=lambda x: (x["count"], -x["std_x"]), reverse=True)
    primary = stable_clusters[0]

    # -------------------------------------------------------------------------
    # Check for Vertical Divider Line (Side-by-Side / Split Stream)
    # -------------------------------------------------------------------------
    divider_x = None
    if frames_for_grad:
        # Search for vertical boundary in [0.32 * W, 0.68 * W]
        grads = []
        for g_frame in frames_for_grad:
            sobelx = cv2.Sobel(g_frame, cv2.CV_64F, 1, 0, ksize=3)
            grads.append(np.mean(np.abs(sobelx), axis=0))
        mean_grad = np.mean(grads, axis=0)
        s_start, s_end = int(width * 0.32), int(width * 0.68)
        search_region = mean_grad[s_start:s_end]
        peak_idx = int(np.argmax(search_region))
        peak_val = search_region[peak_idx]
        median_val = np.median(search_region)
        # Strong vertical edge peak
        if peak_val > max(12.0, median_val * 2.2):
            candidate_div = s_start + peak_idx
            # Verify the face sits cleanly on one side of this divider
            if (candidate_div < primary["cx"] and primary["cx_frac"] > 0.52) or \
               (candidate_div > primary["cx"] and primary["cx_frac"] < 0.48):
                divider_x = candidate_div
                logger.info("Found strong vertical stream divider at x=%d (ratio=%.3f)", divider_x, divider_x / width)

    # =========================================================================
    # CASE 1: Side-by-Side Split Stream (e.g. Chess streams, screen + camera)
    # =========================================================================
    # In side-by-side streams, the streamer occupies an entire half of the screen,
    # so their face is prominently large (h_frac >= 0.20) and sits on one side.
    side_candidates = [
        c for c in stable_clusters
        if c["h_frac"] >= 0.20 and (c["cx_frac"] > 0.52 or c["cx_frac"] < 0.48)
    ]

    if side_candidates and divider_x is not None:
        target = side_candidates[0]
        div_x = divider_x
        face_on_right = target["cx"] > div_x

        if face_on_right:
            # Content is on left [0:div_x], Streamer is on right [div_x:width]
            content_x, content_w = 0, round_to_even(div_x)
            cam_x, cam_w = round_to_even(div_x), round_to_even(width - div_x)
        else:
            # Streamer is on left [0:div_x], Content is on right [div_x:width]
            cam_x, cam_w = 0, round_to_even(div_x)
            content_x, content_w = round_to_even(div_x), round_to_even(width - div_x)

        # Top Tile: Content (1080 x 1040)
        # Bottom Tile: Streamer Camera (1080 x 880) - Zoomed out to show upper body & room
        top_h = 1040
        bottom_h = OUT_H - top_h  # 880

        # Scale content to fit 1080 width, centered vertically
        content_filter = (
            f"crop={content_w}:{height}:{content_x}:0,"
            f"scale={OUT_W}:{top_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"pad={OUT_W}:{top_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )

        # Scale camera: zoomed out to capture whole room, desk, mic
        cam_filter = (
            f"crop={cam_w}:{height}:{cam_x}:0,"
            f"scale={OUT_W}:{bottom_h}:flags=lanczos,setsar=1"
        )

        video_filter = (
            f"[0:v]split=2[csrc][msrc];"
            f"[csrc]{content_filter}[top];"
            f"[msrc]{cam_filter}[bottom];"
            f"[top][bottom]vstack=inputs=2[vout]"
        )

        caption_y = round(top_h / OUT_H, 3)  # Subtitles sit in the middle divider (~0.54)
        logger.info(
            "Configured Side-by-Side layout: Content (%d,%d), Camera (%d,%d), CaptionY=%.2f",
            content_w, height, cam_w, height, caption_y
        )
        return {
            "video_filter": video_filter,
            "mode": "complex",
            "caption_y": caption_y,
            "layout_type": "side_by_side",
        }

    # =========================================================================
    # CASE 2: Corner Facecam Overlay on Fullscreen Game (e.g. CaseOh, Asmongold, GTA, etc.)
    # =========================================================================
    # Twitch-Matched 40/60 Vertical Layout:
    # - Top ~40% (1080 x 760 / 768): Streamer Facecam (high quality Lanczos + unsharp, centered)
    # - Bottom ~60% (1080 x 1160 / 1152): Content / Gameplay centered (captures >52% screen width)
    # - Seamless zero gap (direct vstack, no divider lines or black bands)
    # =========================================================================
    diag = float(np.hypot(width / 2, height / 2))
    corner_candidates = []
    for c in stable_clusters:
        dist_tr = np.hypot(width - c["cx"], c["cy"])
        dist_tl = np.hypot(c["cx"], c["cy"])
        dist_br = np.hypot(width - c["cx"], height - c["cy"])
        dist_bl = np.hypot(c["cx"], height - c["cy"])
        cdist = float(min(dist_tr, dist_tl, dist_br, dist_bl) / diag)
        if cdist < 0.55 and c["h_frac"] < 0.22:
            corner_candidates.append({**c, "corner_dist": cdist})

    if corner_candidates:
        # Pick the most corner-anchored candidate
        corner_candidates.sort(key=lambda x: (x["corner_dist"], -x["count"]))
        webcam = corner_candidates[0]

        top_h = 760    # ~40% of 1920 (matching Twitch portrait aspect 1008x708)
        bottom_h = OUT_H - top_h  # 1160 (~60% of 1920)

        is_left = webcam["cx"] < width / 2

        # Webcam boundary estimation:
        # Match aspect ratio of top tile (OUT_W / top_h = 1080 / 760 = 1.421)
        crop_cam_w = round_to_even(int(min(width * 0.35, max(webcam["w"] * 3.5, width * 0.203))))
        crop_cam_h = round_to_even(int(crop_cam_w * top_h / OUT_W))

        if is_left:
            cam_x = 0
        else:
            cam_x = max(0, width - crop_cam_w)

        # Center on face with headroom & chinroom bounds
        cam_y = int(webcam["cy"] - crop_cam_h * 0.45)
        face_top = webcam["cy"] - webcam["h"] / 2
        if cam_y > face_top - 20:
            cam_y = int(face_top - 20)
        face_bottom = webcam["cy"] + webcam["h"] / 2
        if cam_y + crop_cam_h < face_bottom + 25:
            cam_y = int(face_bottom + 25 - crop_cam_h)

        cam_x = clamp_even(cam_x, 0, width - crop_cam_w)
        cam_y = clamp_even(cam_y, 0, height - crop_cam_h)

        # Content / Gameplay region (Bottom ~60%):
        game_h = height
        game_w = round_to_even(int(game_h * OUT_W / bottom_h))  # 1006 px (captures 52.4% screen width)

        # Center horizontally, shifted cleanly away from the corner webcam
        if is_left:
            game_x = clamp_even(max(cam_x + crop_cam_w + 10, (width - game_w) // 2), 0, width - game_w)
        else:
            game_x = clamp_even(min(cam_x - game_w - 10, (width - game_w) // 2), 0, width - game_w)

        # Seamless vstack: Facecam on TOP, Gameplay on BOTTOM, zero gap, unsharp filter for high sharpness
        video_filter = (
            f"[0:v]split=2[camsrc][gamesrc];"
            f"[camsrc]crop={crop_cam_w}:{crop_cam_h}:{cam_x}:{cam_y},"
            f"scale={OUT_W}:{top_h}:flags=lanczos,unsharp=lx=3:ly=3:la=0.6,setsar=1[top];"
            f"[gamesrc]crop={game_w}:{game_h}:{game_x}:0,"
            f"scale={OUT_W}:{bottom_h}:flags=lanczos,setsar=1[bottom];"
            f"[top][bottom]vstack=inputs=2[vout]"
        )

        caption_y = 0.85
        logger.info(
            "Configured Twitch-Matched 40/60 Layout: Webcam on Top (%d,%d at %d,%d -> %dx%d), Game on Bottom (%d,%d at %d,0 -> %dx%d), CaptionY=%.2f, Zero Gap",
            crop_cam_w, crop_cam_h, cam_x, cam_y, OUT_W, top_h,
            game_w, game_h, game_x, OUT_W, bottom_h,
            caption_y
        )
        return {
            "video_filter": video_filter,
            "mode": "complex",
            "caption_y": caption_y,
            "layout_type": "twitch_vertical_40_60",
        }

    # =========================================================================
    # CASE 3: Single Camera / Fullscreen / Just Chatting
    # =========================================================================
    # If the streamer is full-screen on camera (large face >= 16% screen height,
    # or centered face), crop directly to 9:16 vertical centered on their face.
    # Works universally for ANY streamer in Just Chatting / fullscreen cam mode.
    # =========================================================================
    if primary["h_frac"] >= 0.16 and 0.20 <= primary["cx_frac"] <= 0.80:
        crop_w = round_to_even(int(height * 9 / 16))
        crop_x = clamp_even(int(primary["cx"] - crop_w // 2), 0, width - crop_w)
        video_filter = (
            f"[0:v]crop={crop_w}:{height}:{crop_x}:0,"
            f"scale={OUT_W}:{OUT_H}:flags=lanczos,unsharp=lx=3:ly=3:la=0.5,setsar=1[vout]"
        )
        caption_y = 0.82
        logger.info(
            "Configured Universal Fullscreen 9:16 Layout: crop %dx%d at %d,0 centered on face at x=%d, caption_y=%.2f",
            crop_w, height, crop_x, int(primary["cx"]), caption_y
        )
        return {
            "video_filter": video_filter,
            "mode": "complex",
            "caption_y": caption_y,
            "layout_type": "fullscreen_vertical",
        }

    logger.info("Single camera / full-screen broadcast detected (no split separation needed).")
    return None
