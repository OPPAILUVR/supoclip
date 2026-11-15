import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')

def analyze_visual_actions(video_path: Path, sample_fps: int = 4) -> List[Dict[str, Any]]:
    """
    Lightweight, fast (sample_fps=4) visual motion and facial emotion detector for live buffers.
    Detects:
    - High-kinetic movement (jumping, falling, dancing, desk slams)
    - Screaming / wide mouth opening
    - Laughing / smile clusters
    Returns a list of timestamped visual action events.
    """
    if not video_path.exists():
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_step = max(1, int(orig_fps / sample_fps))
    
    events = []
    prev_gray = None
    prev_face_y = None
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        if frame_idx % frame_step != 0:
            continue
            
        t_sec = frame_idx / orig_fps
        m, s = divmod(int(t_sec), 60)
        time_str = f"{m:02d}:{s:02d}"
        
        # Downscale for rapid processing
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (320, 180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        
        # 1. Optical Flow Kinetic Energy
        kinetic = 0.0
        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 2, 10, 2, 5, 1.1, 0)
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            kinetic = float(np.mean(mag))
            if kinetic > 4.5:
                events.append({
                    "time": time_str,
                    "sec": round(t_sec, 1),
                    "type": "HIGH_KINETIC_MOTION",
                    "detail": f"Sudden explosive physical movement / jump / desk slam (intensity {kinetic:.1f})"
                })
        prev_gray = gray
        
        # 2. Face and Expression Analysis (every second sampled frame)
        if len(events) < 15: # Cap events to avoid cluttering prompt
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=3, minSize=(30, 30))
            if len(faces) > 0:
                faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                (fx, fy, fw, fh) = faces[0]
                
                # Check rapid vertical head jump or slump
                if prev_face_y is not None:
                    dy = fy - prev_face_y
                    if dy < -25:
                        events.append({
                            "time": time_str,
                            "sec": round(t_sec, 1),
                            "type": "CHAIR_JUMP",
                            "detail": "Streamer jumped out of chair / stood up abruptly"
                        })
                    elif dy > 30:
                        events.append({
                            "time": time_str,
                            "sec": round(t_sec, 1),
                            "type": "DESK_COLLAPSE",
                            "detail": "Streamer slumped down / desk slam / falling back"
                        })
                prev_face_y = fy
                
                # Check mouth open ratio (screaming / yelling)
                mouth_roi = gray[fy + int(fh*0.65):fy + fh, fx:fx + fw]
                if mouth_roi.size > 0:
                    _, thresh = cv2.threshold(mouth_roi, 45, 255, cv2.THRESH_BINARY_INV)
                    open_ratio = np.sum(thresh == 255) / thresh.size
                    if open_ratio > 0.40 and kinetic > 1.8:
                        events.append({
                            "time": time_str,
                            "sec": round(t_sec, 1),
                            "type": "SCREAM_RAGE_EXPRESSION",
                            "detail": f"Wide-open mouth screaming / high-arousal rage expression (ratio {open_ratio:.2f})"
                        })
                        
                # Check laughter
                face_roi = gray[fy:fy + fh, fx:fx + fw]
                smiles = smile_cascade.detectMultiScale(face_roi, scaleFactor=1.6, minNeighbors=15, minSize=(15, 15))
                if len(smiles) > 0:
                    events.append({
                        "time": time_str,
                        "sec": round(t_sec, 1),
                        "type": "LAUGHTER_BURST",
                        "detail": "Intense laughing / smiling expression"
                    })

    cap.release()
    
    # Deduplicate events occurring within 2 seconds of each other
    unique_events = []
    last_sec = -999.0
    for ev in events:
        if ev["sec"] - last_sec >= 2.0:
            unique_events.append(ev)
            last_sec = ev["sec"]
            
    return unique_events
