import sys
import subprocess
from pathlib import Path
import cv2
import numpy as np

# Add backend to path for YuNet detector
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from src.media.face_detection import open_yunet_detector

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1152  # 60% of 1920
FACECAM_H = 768   # 40% of 1920


def find_webcam_boundary(frame_gray: np.ndarray, fcx: float, fcy: float, fw: float, fh: float, width: int, height: int) -> int:
    """Find the exact outer vertical edge of a corner webcam box using Sobel column gradient energy."""
    is_left = fcx < width / 2
    y_start = max(0, int(fcy - fh * 0.8))
    y_end = min(height, int(fcy + fh * 0.8))

    if is_left:
        search_x_start = int(fcx + fw * 0.6)
        search_x_end = int(min(width * 0.45, fcx + fw * 3.5))
        if search_x_end <= search_x_start:
            return int(fw * 3.8)

        sub = frame_gray[y_start:y_end, search_x_start:search_x_end]
        sobel = cv2.Sobel(sub, cv2.CV_64F, 1, 0, ksize=3)
        col_energy = np.mean(np.abs(sobel), axis=0)
        peak_idx = int(np.argmax(col_energy))
        best_x = search_x_start + peak_idx
        return best_x
    else:
        search_x_start = int(max(width * 0.55, fcx - fw * 3.5))
        search_x_end = int(fcx - fw * 0.6)
        if search_x_end <= search_x_start:
            return int(width - fw * 3.8)

        sub = frame_gray[y_start:y_end, search_x_start:search_x_end]
        sobel = cv2.Sobel(sub, cv2.CV_64F, 1, 0, ksize=3)
        col_energy = np.mean(np.abs(sobel), axis=0)
        peak_idx = int(np.argmax(col_energy))
        best_x = search_x_start + peak_idx
        return best_x


def analyze_and_render_40_60(input_video: str, output_video: str, start_sec: float = 5.0, duration_sec: float = 30.0):
    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video {input_video}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    detector = open_yunet_detector()
    if not detector:
        raise RuntimeError("YuNet face detector could not be loaded")

    # Sample 15 frames across requested range
    sample_times = np.linspace(start_sec, start_sec + duration_sec, 15)
    detections = []
    sample_frames = []

    print(f"Analyzing {input_video} ({width}x{height}) for 40/60 layout...")
    for t in sample_times:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        sample_frames.append(frame)
        boxes = detector.detect(frame)
        for b in boxes:
            if b[4] >= 0.70:
                detections.append({"t": t, "box": b})
    cap.release()

    if not detections:
        raise RuntimeError("No face detected in video")

    # Cluster detections to find stationary streamer
    clusters = []
    for d in detections:
        bx, by, bw, bh, score = d["box"]
        cx, cy = bx + bw / 2, by + bh / 2
        matched = False
        for c in clusters:
            if abs(cx - c["cx"]) < 100 and abs(cy - c["cy"]) < 100:
                c["boxes"].append(d["box"])
                c["cx"] = float(np.mean([b[0] + b[2] / 2 for b in c["boxes"]]))
                c["cy"] = float(np.mean([b[1] + b[3] / 2 for b in c["boxes"]]))
                matched = True
                break
        if not matched:
            clusters.append({"cx": cx, "cy": cy, "boxes": [d["box"]]})

    diag = float(np.hypot(width, height))
    for c in clusters:
        dist_tl = np.hypot(c["cx"], c["cy"])
        dist_tr = np.hypot(width - c["cx"], c["cy"])
        dist_bl = np.hypot(c["cx"], height - c["cy"])
        dist_br = np.hypot(width - c["cx"], height - c["cy"])
        c["corner_dist"] = min(dist_tl, dist_tr, dist_bl, dist_br) / diag
        c["count"] = len(c["boxes"])

    clusters.sort(key=lambda x: (x["corner_dist"], -x["count"]))
    streamer_cluster = clusters[0]

    boxes = streamer_cluster["boxes"]
    med_x = float(np.median([b[0] for b in boxes]))
    med_y = float(np.median([b[1] for b in boxes]))
    med_w = float(np.median([b[2] for b in boxes]))
    med_h = float(np.median([b[3] for b in boxes]))

    fcx = med_x + med_w / 2
    fcy = med_y + med_h / 2

    print(f"Streamer face detected: center=({fcx:.1f}, {fcy:.1f}), size=({med_w:.1f}x{med_h:.1f})")

    # Detect outer boundary of webcam box
    mid_frame = sample_frames[len(sample_frames) // 2]
    mid_gray = cv2.cvtColor(mid_frame, cv2.COLOR_BGR2GRAY)
    webcam_boundary_x = find_webcam_boundary(mid_gray, fcx, fcy, med_w, med_h, width, height)
    print(f"Detected webcam boundary X: {webcam_boundary_x}")

    is_left = fcx < width / 2
    if is_left:
        cam_x = 0
        cam_w = webcam_boundary_x
    else:
        cam_x = webcam_boundary_x
        cam_w = width - webcam_boundary_x

    # Ensure webcam width is valid
    cam_w = max(int(med_w * 2.5), min(cam_w, int(width * 0.40)))

    # 40% tile is 1080 x 768 (aspect ratio 1.406).
    # Normal aspect ratio height would be int(cam_w * 768 / 1080).
    # Squeezed 10% vertically to capture 10% more vertical space down to the frame bottom:
    norm_h = int(cam_w * FACECAM_H / OUT_W)
    cam_h = int(norm_h * 1.10)  # 10% vertical squeeze

    # Center crop on face with headroom & chinroom guards
    cam_y = int(fcy - cam_h * 0.45)
    if cam_y > med_y - 25:
        cam_y = int(med_y - 25)
    if cam_y + cam_h < med_y + med_h + 30:
        cam_y = int(med_y + med_h + 30 - cam_h)

    # Frame clamps
    cam_x = max(0, min(width - cam_w, cam_x))
    cam_y = max(0, min(height - cam_h, cam_y))

    # If stream bottom is reachable, extend to stream bottom so zero chin is cut
    if cam_y + cam_h >= height - 20:
        cam_y = height - cam_h

    # Even dimensions
    cam_w = (cam_w // 2) * 2
    cam_h = (cam_h // 2) * 2
    cam_x = (cam_x // 2) * 2
    cam_y = (cam_y // 2) * 2

    print(f"40% Facecam Crop: x={cam_x}, y={cam_y}, w={cam_w}, h={cam_h} -> scaled to {OUT_W}x{FACECAM_H}")

    # Top 60% Content Crop: 1080 x 1152
    game_w = int(OUT_W * height / CONTENT_H)  # 1012 px
    game_w = (game_w // 2) * 2
    game_h = height
    # Shift center crop away from the corner webcam to prevent corner leakage
    if is_left:
        game_x = max(cam_w - 26, (width - game_w) // 2)
    else:
        game_x = min(cam_x - game_w + 26, (width - game_w) // 2)
    game_x = ((game_x) // 2) * 2
    game_y = 0

    print(f"60% Content Crop: x={game_x}, y={game_y}, w={game_w}, h={game_h} -> scaled to {OUT_W}x{CONTENT_H}")

    vf = (
        f"[0:v]split=2[camsrc][gamesrc];"
        f"[gamesrc]crop={game_w}:{game_h}:{game_x}:{game_y},"
        f"scale={OUT_W}:{CONTENT_H}:flags=lanczos,setsar=1[top];"
        f"[camsrc]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
        f"scale={OUT_W}:{FACECAM_H}:flags=lanczos,setsar=1[bottom];"
        f"[top][bottom]vstack=inputs=2[stacked];"
        f"[stacked]drawbox=x=0:y={CONTENT_H-2}:w={OUT_W}:h=4:color=white@0.5:t=fill[vout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec), "-t", str(duration_sec),
        "-i", input_video,
        "-filter_complex", vf,
        "-map", "[vout]",
        "-map", "0:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]

    print("Executing FFmpeg render...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("FFmpeg error:", res.stderr)
        sys.exit(1)

    print("Render complete! Saved to:", output_video)


if __name__ == "__main__":
    in_vid = sys.argv[1]
    out_vid = sys.argv[2]
    start = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    dur = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0
    analyze_and_render_40_60(in_vid, out_vid, start, dur)
