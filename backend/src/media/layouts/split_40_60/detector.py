"""Universal Streamer Facecam + Gameplay Detection for 40/60 Split Vertical Layout."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from ...face_detection import open_yunet_detector
from .filter_builder import (
    build_corner_40_60_filter,
    build_fullscreen_9_16_filter,
    build_side_by_side_filter,
)

logger = logging.getLogger(__name__)


def detect_streamer_layout(
    video_path: Path,
    width: int,
    height: int,
    max_samples: int = 16,
) -> Optional[Dict[str, Any]]:
    """Detect streamer layout and build the optimal 9:16 layout filter.

    Returns dict with {'video_filter': str, 'mode': 'complex', 'caption_y': float, 'layout_type': str}
    or None if no face cluster is detected so callers can apply deterministic fallback.
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
                if b[4] >= 0.65:
                    face_detections.append({"t": t, "box": b})
    finally:
        cap.release()

    if not face_detections:
        return None

    # Cluster detections by spatial proximity (< 120px)
    clusters: List[Dict[str, Any]] = []
    for d in face_detections:
        bx, by, bw, bh, _ = d["box"]
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

    stable_clusters.sort(key=lambda x: (x["count"], -x["std_x"]), reverse=True)
    primary = stable_clusters[0]

    # Check for vertical divider line (Side-by-Side / Split Stream)
    divider_x = None
    if frames_for_grad:
        grads = [
            np.mean(np.abs(cv2.Sobel(g_frame, cv2.CV_64F, 1, 0, ksize=3)), axis=0)
            for g_frame in frames_for_grad
        ]
        mean_grad = np.mean(grads, axis=0)
        s_start, s_end = int(width * 0.32), int(width * 0.68)
        search_region = mean_grad[s_start:s_end]
        peak_idx = int(np.argmax(search_region))
        peak_val = search_region[peak_idx]
        median_val = np.median(search_region)
        if peak_val > max(12.0, median_val * 2.2):
            candidate_div = s_start + peak_idx
            if (candidate_div < primary["cx"] and primary["cx_frac"] > 0.52) or (
                candidate_div > primary["cx"] and primary["cx_frac"] < 0.48
            ):
                divider_x = candidate_div
                logger.info("Found strong vertical stream divider at x=%d (ratio=%.3f)", divider_x, divider_x / width)

    # CASE 1: Side-by-Side Split Stream
    side_candidates = [
        c for c in stable_clusters
        if c["h_frac"] >= 0.20 and (c["cx_frac"] > 0.52 or c["cx_frac"] < 0.48)
    ]
    if side_candidates and divider_x is not None:
        face_on_right = side_candidates[0]["cx"] > divider_x
        return build_side_by_side_filter(width, height, divider_x, face_on_right)

    # CASE 2: Corner Facecam Overlay (40/60 Vertical Split)
    diag = float(np.hypot(width / 2, height / 2))
    corner_candidates = []
    for c in stable_clusters:
        cdist = float(
            min(
                np.hypot(width - c["cx"], c["cy"]),
                np.hypot(c["cx"], c["cy"]),
                np.hypot(width - c["cx"], height - c["cy"]),
                np.hypot(c["cx"], height - c["cy"]),
            )
            / diag
        )
        if cdist < 0.55 and c["h_frac"] < 0.22:
            corner_candidates.append({**c, "corner_dist": cdist})

    if corner_candidates:
        corner_candidates.sort(key=lambda x: (x["corner_dist"], -x["count"]))
        return build_corner_40_60_filter(width, height, corner_candidates[0])

    # CASE 3: Single Camera / Fullscreen / Just Chatting
    if primary["h_frac"] >= 0.16 and 0.20 <= primary["cx_frac"] <= 0.80:
        return build_fullscreen_9_16_filter(width, height, primary["cx"])

    logger.info("Single camera / full-screen broadcast detected (no split separation needed).")
    return None
