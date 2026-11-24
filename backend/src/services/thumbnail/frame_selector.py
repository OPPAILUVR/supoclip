"""Dual-Frame Climax & Action Hotspot Selector for High-CTR Thumbnails.

Independently locates:
  1. Peak Facial Reaction Frame (largest/most expressive face in webcam zone)
  2. Peak Visual Action Frame + Action Hotspot coordinates (fire, explosions, cars, intense contrast)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    from ...media.face_detection import YuNetFaceDetector
except ImportError:
    YuNetFaceDetector = None

logger = logging.getLogger("ThumbnailGenerator")

FaceBox = Tuple[float, float, float, float]
Point = Tuple[float, float]


def _detect_action_hotspot(game_bgr: np.ndarray) -> Tuple[float, float]:
    """Locate the most visually dramatic focal point in the gameplay/scene half.

    Combines fiery saturation/brightness spikes + high-frequency gradient edges,
    penalizing HUD corners so arrows/zoom-circles land on real action (cars, fire, faces, explosions).
    """
    h, w = game_bgr.shape[:2]
    if h < 40 or w < 40:
        return (w * 0.5, h * 0.5)

    hsv = cv2.cvtColor(game_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    gray = cv2.cvtColor(game_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Edge / texture density
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(gx * gx + gy * gy)

    # Fire / bright neon / vehicle taillights / high-contrast subjects (reject green tree foliage & sky!)
    sat = hsv[..., 1] / 255.0
    val = hsv[..., 2] / 255.0
    hue = hsv[..., 0]  # 0..179 in OpenCV
    warm_mask = ((hue <= 28) | (hue >= 160)).astype(np.float32)
    foliage_or_sky = ((hue >= 34) & (hue <= 105)).astype(np.float32)

    # Low-pass structure score (objects/vehicles/fire) rather than fine leaf edges
    smooth_grad = cv2.GaussianBlur(grad_mag / 255.0, (25, 25), 0)
    saliency = smooth_grad * 0.40 + (sat * val) * 0.90 + (warm_mask * val * (0.4 + sat)) * 1.45
    saliency *= (1.0 - foliage_or_sky * 0.78)
    saliency = cv2.GaussianBlur(saliency, (55, 55), 0)

    # Focus squarely on center action band (vehicles, players, explosions), avoiding top text band & bottom subtitles
    y_grid, x_grid = np.mgrid[0:h, 0:w]
    weight = np.ones((h, w), dtype=np.float32)
    weight[y_grid < int(h * 0.28)] = 0.0
    weight[y_grid > int(h * 0.68)] = 0.0
    weight[(x_grid < int(w * 0.14)) | (x_grid > int(w * 0.86))] *= 0.25

    weighted = saliency * weight
    _, _, _, max_loc = cv2.minMaxLoc(weighted)
    hx, hy = float(max_loc[0]), float(max_loc[1])
    return (hx, hy)


def _score_face_intensity(gray: np.ndarray, fx: float, fy: float, fw: float, fh: float, conf: float) -> float:
    """Estimate facial shock/expression intensity (mouth open / wide contrast / large scale)."""
    h, w = gray.shape[:2]
    x1, y1 = max(0, int(fx)), max(0, int(fy))
    x2, y2 = min(w, int(fx + fw)), min(h, int(fy + fh))
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0
    face_lap = float(cv2.Laplacian(roi, cv2.CV_64F).var())
    # Mouth region variance/darkness (open mouth yelling/shock has higher contrast in lower third of face)
    mh1 = y1 + int((y2 - y1) * 0.58)
    mouth_roi = gray[mh1:y2, x1:x2]
    mouth_contrast = float(mouth_roi.std()) if mouth_roi.size > 0 else 0.0
    return (fw * fh) * 0.35 + face_lap * 2.0 + mouth_contrast * 18.0 + conf * 3500.0


def extract_best_climax_composite(
    video_path: Path,
) -> Tuple[np.ndarray, float, Optional[FaceBox], Point]:
    """Select Peak Face Reaction + Peak Gameplay Action and composite into a 1080x1920 frame.

    If the video is a 40/60 split (facecam detected in Y < 760), the top 40% uses the
    sharpest/most expressive face frame (zoom-punched cleanly onto the streamer!) and
    the bottom 60% uses the highest-action climax frame (fire, explosion, crash, motion).

    Returns:
        (composite_bgr_1080x1920, chosen_timestamp_sec, face_box_in_1080x1920, action_hotspot_in_1080x1920)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"Cannot open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0.0

    yunet = None
    if YuNetFaceDetector:
        try:
            yunet = YuNetFaceDetector(score_threshold=0.45)
        except Exception as e:
            logger.debug("YuNet detector init notice (falling back to Haar): %s", e)

    haar_cascade = None
    if not yunet:
        try:
            haar_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            pass

    start_f = max(0, int(total_frames * 0.12))
    end_f = min(total_frames - 1, int(total_frames * 0.88))
    if start_f >= end_f:
        start_f = 0
        end_f = max(0, total_frames - 1)

    step = max(1, int(fps * 0.35))

    best_face_frame = None
    best_face_score = -1.0
    best_face_box: Optional[FaceBox] = None
    best_face_sec = duration / 2.0

    best_action_frame = None
    best_action_score = -1.0
    best_action_sec = duration / 2.0

    prev_small_gray = None

    for f_idx in range(start_f, end_f + 1, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Score facial emotion — strongly prefer upper webcam zone (fy + fh/2 < 0.43 * h) over game NPCs
        primary_box: Optional[FaceBox] = None
        f_score = 0.0

        if yunet:
            faces = yunet.detect(frame)
            if faces:
                top_faces = [f for f in faces if (f[1] + f[3] / 2.0) < h * 0.43]
                pool = top_faces if top_faces else faces
                faces_sorted = sorted(pool, key=lambda f: f[2] * f[3], reverse=True)
                fx, fy, fw, fh, conf = faces_sorted[0]
                primary_box = (float(fx), float(fy), float(fw), float(fh))
                f_score = _score_face_intensity(gray, fx, fy, fw, fh, conf)
                if top_faces:
                    f_score += 25000.0  # Prioritize streamer webcam face over random bottom NPCs
        elif haar_cascade is not None:
            faces = haar_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))
            if len(faces) > 0:
                top_faces = [f for f in faces if (f[1] + f[3] / 2.0) < h * 0.43]
                pool = top_faces if top_faces else list(faces)
                largest = max(pool, key=lambda b: b[2] * b[3])
                primary_box = (float(largest[0]), float(largest[1]), float(largest[2]), float(largest[3]))
                f_score = _score_face_intensity(gray, *primary_box, 0.8)
                if top_faces:
                    f_score += 25000.0

        # Add general crispness to avoid blurry frames
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if primary_box is not None and f_score + lap_var * 0.3 > best_face_score:
            best_face_score = f_score + lap_var * 0.3
            best_face_frame = frame.copy()
            best_face_box = primary_box
            best_face_sec = f_idx / fps

        # 2. Score action intensity (especially lower 60% gameplay region)
        action_roi = frame[int(h * 0.40):, :] if h > 400 else frame
        hsv_a = cv2.cvtColor(action_roi, cv2.COLOR_BGR2HSV)
        sat_mean = float(hsv_a[..., 1].mean())
        val_std = float(hsv_a[..., 2].std())
        bright_fire = float(np.mean((hsv_a[..., 2] > 210) & (hsv_a[..., 1] > 110))) * 6000.0
        action_lap = float(cv2.Laplacian(cv2.cvtColor(action_roi, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

        small_gray = cv2.resize(cv2.cvtColor(action_roi, cv2.COLOR_BGR2GRAY), (160, 96))
        motion_diff = 0.0
        if prev_small_gray is not None:
            motion_diff = float(np.mean(cv2.absdiff(small_gray, prev_small_gray))) * 45.0
        prev_small_gray = small_gray

        a_score = action_lap * 0.9 + val_std * 32.0 + sat_mean * 18.0 + bright_fire + motion_diff
        if a_score > best_action_score:
            best_action_score = a_score
            best_action_frame = frame.copy()
            best_action_sec = f_idx / fps

    cap.release()

    if best_action_frame is None:
        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        _, best_action_frame = cap.read()
        cap.release()
        best_action_sec = duration / 2.0

    if best_face_frame is None:
        best_face_frame = best_action_frame.copy()

    # Resize both to canonical 1080x1920 before compositing
    def _to_1080_1920(bgr: np.ndarray) -> np.ndarray:
        if bgr.shape[1] != 1080 or bgr.shape[0] != 1920:
            return cv2.resize(bgr, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
        return bgr

    face_canvas = _to_1080_1920(best_face_frame)
    action_canvas = _to_1080_1920(best_action_frame)

    # Normalize best_face_box to 1080x1920 space if source resolution differed
    if best_face_box is not None and best_face_frame is not None:
        orig_h, orig_w = best_face_frame.shape[:2]
        sx, sy = 1080.0 / max(1, orig_w), 1920.0 / max(1, orig_h)
        fx, fy, fw, fh = best_face_box
        best_face_box = (fx * sx, fy * sy, fw * sx, fh * sy)

    # Check if this is a 40/60 split clip (face sits inside top Y: [0, 760])
    is_top_split = best_face_box is not None and (best_face_box[1] + best_face_box[3] / 2.0) < 760

    if is_top_split and best_face_box is not None:
        # Composite Peak Face (Top 760px, zoomed 1.24x around face center for huge presence!)
        # + Peak Action (Bottom 1160px)
        composite = action_canvas.copy()
        top_cam = face_canvas[0:760, 0:1080]

        fx, fy, fw, fh = best_face_box
        fcx = fx + fw / 2.0
        fcy = fy + fh * 0.45
        zoom = 1.24
        crop_w = int(1080 / zoom)
        crop_h = int(760 / zoom)
        x1 = int(max(0, min(1080 - crop_w, fcx - crop_w / 2.0)))
        y1 = int(max(0, min(760 - crop_h, fcy - crop_h / 2.0)))
        zoomed_cam = cv2.resize(top_cam[y1 : y1 + crop_h, x1 : x1 + crop_w], (1080, 760), interpolation=cv2.INTER_LANCZOS4)
        composite[0:760, 0:1080] = zoomed_cam

        # Re-project face box into zoomed 1080x760 coordinates
        new_fx = (fx - x1) * zoom
        new_fy = (fy - y1) * zoom
        best_face_box = (new_fx, new_fy, fw * zoom, fh * zoom)

        game_half = composite[760:1920, 0:1080]
        hx_local, hy_local = _detect_action_hotspot(game_half)
        action_hotspot = (hx_local, 760.0 + hy_local)
        chosen_sec = best_action_sec
    else:
        composite = face_canvas
        hx_local, hy_local = _detect_action_hotspot(composite[760:1920, :])
        action_hotspot = (hx_local, 760.0 + hy_local)
        chosen_sec = best_face_sec

    logger.info(
        "Dual-frame climax composite ready (face@%.2fs, action@%.2fs, hotspot=(%.0f, %.0f))",
        best_face_sec, best_action_sec, action_hotspot[0], action_hotspot[1],
    )
    return composite, chosen_sec, best_face_box, action_hotspot
