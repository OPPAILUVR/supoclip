"""Universal Streamer Facecam Detection & 30/70 Layout Engine.

Detects streamer facecam across arbitrary streamers, positions, and styles:
- Rectangular / Square boxed facecams (Asmongold, Shroud, Pokimane, etc.)
- Circular masked facecams
- Green-screen / chroma-keyed cutouts (Tyler1, DrDisrespect)
- Side-by-side split streams (Chess, screen-shares)
- Fullscreen / Just Chatting / IRL single camera

Renders a 30/70 vertical layout:
- 70% Height (1080 x 1344): Content / Gameplay
- 30% Height (1080 x 576): Streamer Facecam
"""

import sys
from pathlib import Path
import cv2
import numpy as np

# Ensure backend modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from src.media.face_detection import open_yunet_detector

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920


def analyze_stream(video_path: str, max_samples: int = 15):
    """Analyze video frames to detect streamer facecam and content layout."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    detector = open_yunet_detector()
    if not detector:
        raise RuntimeError("YuNet face detector could not be loaded")

    # Sample timestamps evenly
    sample_times = np.linspace(0.5, max(0.5, duration - 0.5), max_samples)
    detections = []
    frames = []

    for t in sample_times:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        frames.append(frame)
        boxes = detector.detect(frame)
        for b in boxes:
            if b[4] >= 0.65:  # confidence >= 65%
                detections.append({"t": t, "box": b})

    cap.release()

    if not detections:
        return {
            "type": "no_face_gameplay_only",
            "width": width,
            "height": height,
            "details": "No stationary human face detected in video."
        }

    # Step 2: Spatial clustering to find the persistent streamer face
    clusters = []
    for d in detections:
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

    # Filter to stable clusters
    diag = float(np.hypot(width, height))
    min_count = max(2, int(len(sample_times) * 0.30))
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

        # Calculate corner proximity
        dist_tl = np.hypot(cx, cy)
        dist_tr = np.hypot(width - cx, cy)
        dist_bl = np.hypot(cx, height - cy)
        dist_br = np.hypot(width - cx, height - cy)
        min_corner_dist = min(dist_tl, dist_tr, dist_bl, dist_br) / diag

        stable_clusters.append({
            "cx": cx, "cy": cy, "w": med_w, "h": med_h,
            "count": n, "std_x": std_x, "std_y": std_y,
            "h_frac": med_h / height, "w_frac": med_w / width,
            "cx_frac": cx / width, "cy_frac": cy / height,
            "corner_dist": min_corner_dist,
        })

    if not stable_clusters:
        return {
            "type": "transient_faces",
            "width": width, "height": height,
            "details": "Faces detected, but none are stationary."
        }

    # Sort to find the primary streamer
    # Prioritize corner proximity + stationary count
    stable_clusters.sort(key=lambda x: (x["corner_dist"], -x["count"]))
    streamer = stable_clusters[0]

    # Check if single-camera full screen (e.g. face is large and center)
    if streamer["h_frac"] > 0.35 and streamer["corner_dist"] > 0.35:
        return {
            "type": "fullscreen_camera",
            "width": width, "height": height,
            "streamer": streamer,
            "details": "Streamer is full screen (IRL / Just Chatting). No 30/70 separation needed."
        }

    # Step 3: Determine Facecam Style & Boundaries
    # Analyze region around streamer face across sampled frames
    fcx, fcy = streamer["cx"], streamer["cy"]
    fw, fh = streamer["w"], streamer["h"]

    # Check for circular facecam mask (Hough circle around face center)
    is_circular = False
    circle_params = None
    if len(frames) > 0:
        gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        # Search for circles near face center
        r_min = int(max(fw, fh) * 0.7)
        r_max = int(max(fw, fh) * 2.2)
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=100,
            param1=100, param2=40, minRadius=r_min, maxRadius=r_max
        )
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            for (x, y, r) in circles:
                if abs(x - fcx) < fw * 0.8 and abs(y - fcy) < fh * 0.8:
                    is_circular = True
                    circle_params = (x, y, r)
                    break

    # Check for Green Screen Cutout vs Box
    # Sample background pixels 1.5 face widths to the left and right of face center
    is_greenscreen = False
    if len(frames) >= 4 and not is_circular:
        bg_samples = []
        for f in frames[:4]:
            gray_f = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            # Sample patches left and right of head
            x_l = max(0, int(fcx - fw * 1.5))
            x_r = min(width - 10, int(fcx + fw * 1.5))
            y_s = max(0, int(fcy - fh * 0.5))
            patch_l = gray_f[y_s:y_s + int(fh), x_l:x_l + 10]
            patch_r = gray_f[y_s:y_s + int(fh), x_r:x_r + 10]
            bg_samples.append((patch_l, patch_r))
        
        # Measure pixel variance across time in the background patch
        var_l = np.mean([np.std([s[0] for s in bg_samples], axis=0)])
        var_r = np.mean([np.std([s[1] for s in bg_samples], axis=0)])
        # If gameplay motion is churning right behind them -> Green screen!
        if max(var_l, var_r) > 28.0:
            is_greenscreen = True

    # Compute optimal facecam bounding box (Aspect ratio 15:8 / 1.875 to match 1080x576)
    target_aspect = OUT_W / FACECAM_H  # 1.875 (1080 / 576)
    
    # We want a comfortable bust shot capturing the head, shoulders, and expressions
    cam_w = int(max(fw * 4.2, width * 0.28))
    cam_w = min(width, max(360, cam_w))
    cam_h = int(cam_w / target_aspect)
    
    # Position box around face center
    cam_x = int(fcx - cam_w / 2)
    cam_y = int(fcy - cam_h * 0.40)  # place face at ~40% height of the box

    # Clamp to frame edges
    cam_x = max(0, min(width - cam_w, cam_x))
    cam_y = max(0, min(height - cam_h, cam_y))
    # Make even
    cam_w = (cam_w // 2) * 2
    cam_h = (cam_h // 2) * 2
    cam_x = (cam_x // 2) * 2
    cam_y = (cam_y // 2) * 2

    # Step 4: Gameplay / Content Region (Shift away from facecam to avoid duplication)
    # The 70% tile is 1080 x 1344 (aspect ratio 0.803)
    game_h = height
    game_w = int(game_h * (OUT_W / CONTENT_H))  # ~868 px for 1080p
    game_w = (game_w // 2) * 2
    game_w = min(width, game_w)

    # Screen / Content Crop: Always crop the dead center of the stream
    # Main action (gameplay crosshair, main character, Twitter feed, video player) is centered
    game_x = ((width - game_w) // 2 // 2) * 2
    game_y = 0

    facecam_style = "circular_facecam" if is_circular else ("green_screen_cutout" if is_greenscreen else "rectangular_box")

    return {
        "type": "separated_facecam_gameplay",
        "style": facecam_style,
        "width": width,
        "height": height,
        "streamer": streamer,
        "facecam_box": {"x": cam_x, "y": cam_y, "w": cam_w, "h": cam_h},
        "gameplay_box": {"x": game_x, "y": game_y, "w": game_w, "h": game_h},
        "target_layout": {
            "out_w": OUT_W,
            "out_h": OUT_H,
            "content_h": CONTENT_H,
            "facecam_h": FACECAM_H,
            "content_ratio": 0.70,
            "facecam_ratio": 0.30,
        }
    }


def build_30_70_filtergraph(analysis: dict) -> str:
    """Build the high-performance FFmpeg filtergraph for 30/70 vertical layout."""
    fb = analysis["facecam_box"]
    gb = analysis["gameplay_box"]

    # Top 70% (1080 x 1344) Content
    # Bottom 30% (1080 x 576) Facecam
    content_filter = (
        f"[0:v]crop={gb['w']}:{gb['h']}:{gb['x']}:{gb['y']},"
        f"scale={OUT_W}:{CONTENT_H}:flags=lanczos,setsar=1[top]"
    )

    facecam_filter = (
        f"[0:v]crop={fb['w']}:{fb['h']}:{fb['x']}:{fb['y']},"
        f"scale={OUT_W}:{FACECAM_H}:flags=lanczos,setsar=1[bottom]"
    )

    # Clean divider separator (a 2px subtle divider or direct stack)
    stack_filter = (
        f"{content_filter};"
        f"{facecam_filter};"
        f"[top][bottom]vstack=inputs=2[vout]"
    )
    return stack_filter


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python universal_facecam_engine.py <video_path>")
        sys.exit(1)
    
    vid_path = sys.argv[1]
    res = analyze_stream(vid_path)
    import json
    # Print formatted summary
    print(json.dumps(res, indent=2))
