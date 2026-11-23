#!/usr/bin/env python3
"""
Deep Multimodal Video & Frame-by-Frame Emotion Analysis.
Processes representative viral GTA shorts:
- Audio transcription via Whisper
- Frame-by-frame OpenCV facial recognition (Haar cascades for face, smile/laugh, eyes/shock)
- Optical flow / motion energy dynamics
- Hook & narrative pacing breakdown (0-3s hook, tension build, climax, reaction)
"""

import os
import sys
import json
import time
from pathlib import Path
import cv2
import numpy as np
import yt_dlp
import whisper

STUDY_DIR = Path("/Users/luv/.gemini/antigravity/scratch/supoclip/research/gta_study")
SAMPLES_DIR = STUDY_DIR / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = STUDY_DIR / "deep_video_profiles.json"

FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
SMILE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")
EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

SAMPLE_TARGETS = [
    {"id": "5uSkzsRNNlI", "category": "xqc_heists_malding", "title": "Xqc Gets “BANNED” Live… | NoPixel V GTA RP"},
    {"id": "lk0HaySCvgY", "category": "high_stakes_escapes", "title": "The RATTIEST Way To Escape Police In GTA RP?"},
    {"id": "6K0DZGpbhSA", "category": "stunts_ragdoll_fails", "title": "xQc jumps off a cliff in the New Remastered GTA San Andreas..."},
    {"id": "9hyLBw6WjGs", "category": "speed_high_energy_reactions", "title": "iShowSpeed Reacts To His GTA 4 Loading Screen Meme 😭💀"},
    {"id": "3EdlqLrPsn8", "category": "streamer_comedy_banter", "title": "Adam Falls For Amon Gus Name - GTA RP Funny Moments"},
    {"id": "knyy9X20s6U", "category": "roleplay_comedy_banter", "title": "Sykkuno fluently TRANSLATES xQc's Juicer LANGUAGE (how)"},
]

def download_video(vid_id):
    target_path = SAMPLES_DIR / f"{vid_id}.mp4"
    if target_path.exists() and target_path.stat().st_size > 50000:
        return target_path
    
    url = f"https://www.youtube.com/shorts/{vid_id}"
    ydl_opts = {
        "format": "best[height<=720][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(target_path),
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if target_path.exists():
            return target_path
    except Exception as e:
        print(f"Failed to download {vid_id}: {e}")
    return None

def transcribe_audio(model, video_path):
    try:
        res = model.transcribe(str(video_path), fp16=False)
        segments = []
        for s in res.get("segments", []):
            segments.append({
                "start": round(s.get("start", 0), 2),
                "end": round(s.get("end", 0), 2),
                "text": s.get("text", "").strip()
            })
        return {
            "full_transcript": res.get("text", "").strip(),
            "segments": segments,
            "language": res.get("language", "en")
        }
    except Exception as e:
        print(f"Transcription error on {video_path}: {e}")
        return {"full_transcript": "", "segments": [], "language": "unknown"}

def analyze_frames(video_path):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / fps

    face_detected_frames = 0
    smile_frames = 0
    shock_frames = 0
    prev_gray = None
    motion_energies = []
    face_positions = []
    
    # Track emotional intensity over time (per second)
    second_emotions = []
    current_sec = 0
    sec_faces = 0
    sec_smiles = 0
    sec_shocks = 0
    sec_motion = []

    step = max(1, int(fps / 6)) # Sample at ~6 FPS
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_idx / fps
        sec_idx = int(timestamp)

        if sec_idx > current_sec:
            second_emotions.append({
                "second": current_sec,
                "face_present": sec_faces > 0,
                "smile_count": sec_smiles,
                "shock_count": sec_shocks,
                "avg_motion": round(float(np.mean(sec_motion)), 2) if sec_motion else 0.0
            })
            current_sec = sec_idx
            sec_faces = 0
            sec_smiles = 0
            sec_shocks = 0
            sec_motion = []

        if frame_idx % step == 0:
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Motion diff
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                energy = float(np.mean(diff))
                motion_energies.append(energy)
                sec_motion.append(energy)
            prev_gray = gray

            # Face recognition
            faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(50, 50))
            if len(faces) > 0:
                face_detected_frames += 1
                sec_faces += 1
                fx, fy, fw, fh = faces[0]
                face_roi = gray[fy:fy+fh, fx:fx+fw]

                # Quadrant
                qx = "right" if (fx + fw/2) > w/2 else "left"
                qy = "bottom" if (fy + fh/2) > h/2 else "top"
                face_positions.append(f"{qy}_{qx}")

                # Smiles
                smiles = SMILE_CASCADE.detectMultiScale(face_roi, scaleFactor=1.7, minNeighbors=20, minSize=(20, 20))
                if len(smiles) > 0:
                    smile_frames += 1
                    sec_smiles += 1

                # Eyes / Shock
                eyes = EYE_CASCADE.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=5, minSize=(15, 15))
                if len(eyes) >= 2:
                    shock_frames += 1
                    sec_shocks += 1

        frame_idx += 1

    cap.release()

    samples_count = max(1, frame_idx // step)
    pos_counts = {}
    for p in face_positions:
        pos_counts[p] = pos_counts.get(p, 0) + 1
    dominant_pos = max(pos_counts.items(), key=lambda x: x[1])[0] if pos_counts else "none"

    # Peak reaction identification
    peak_smile_sec = max(second_emotions, key=lambda x: x["smile_count"])["second"] if second_emotions else 0
    peak_shock_sec = max(second_emotions, key=lambda x: x["shock_count"])["second"] if second_emotions else 0
    peak_motion_sec = max(second_emotions, key=lambda x: x["avg_motion"])["second"] if second_emotions else 0

    return {
        "duration_s": round(duration_s, 2),
        "total_frames": total_frames,
        "fps": round(fps, 1),
        "facecam": {
            "present": face_detected_frames > (samples_count * 0.15),
            "presence_ratio": round(face_detected_frames / samples_count, 3),
            "dominant_quadrant": dominant_pos,
        },
        "emotions": {
            "laughter_frames_ratio": round(smile_frames / max(1, face_detected_frames), 3),
            "shock_frames_ratio": round(shock_frames / max(1, face_detected_frames), 3),
            "peak_laughter_timestamp_s": peak_smile_sec,
            "peak_shock_timestamp_s": peak_shock_sec,
        },
        "gameplay_dynamics": {
            "avg_motion_energy": round(float(np.mean(motion_energies)), 2) if motion_energies else 0.0,
            "max_motion_energy": round(float(np.max(motion_energies)), 2) if motion_energies else 0.0,
            "peak_motion_timestamp_s": peak_motion_sec,
        },
        "second_by_second_profile": second_emotions[:15] # first 15 seconds profile
    }

def main():
    print("Loading Whisper model (base)...")
    whisper_model = whisper.load_model("base")
    print("Whisper model loaded successfully.")

    results = []
    for item in SAMPLE_TARGETS:
        vid_id = item["id"]
        title = item["title"]
        cat = item["category"]
        print(f"\n==================================================")
        print(f"Processing Target: [{vid_id}] {title}")
        print(f"Category: {cat}")
        
        path = download_video(vid_id)
        if not path:
            print(f"Skipping {vid_id} - could not download.")
            continue
        
        print(f"Downloaded video to {path} ({round(path.stat().st_size / 1024 / 1024, 2)} MB)")
        
        print("Transcribing audio...")
        transcript_data = transcribe_audio(whisper_model, path)
        print(f"Transcript ({len(transcript_data['full_transcript'])} chars): {transcript_data['full_transcript'][:120]}...")

        print("Analyzing frames (Facecam, Emotions, Motion Energy)...")
        frame_data = analyze_frames(path)
        if frame_data:
            print(f"Duration: {frame_data['duration_s']}s | Facecam: {frame_data['facecam']['dominant_quadrant']} (presence {frame_data['facecam']['presence_ratio']*100:.1f}%)")
            print(f"Emotions: Laughter ratio={frame_data['emotions']['laughter_frames_ratio']} | Shock ratio={frame_data['emotions']['shock_frames_ratio']}")
            print(f"Climax Timestamps: Laughter @ {frame_data['emotions']['peak_laughter_timestamp_s']}s, Shock @ {frame_data['emotions']['peak_shock_timestamp_s']}s, Motion @ {frame_data['gameplay_dynamics']['peak_motion_timestamp_s']}s")

        res_record = {
            "id": vid_id,
            "title": title,
            "category": cat,
            "transcript": transcript_data,
            "frame_analysis": frame_data
        }
        results.append(res_record)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nSUCCESS: Deep video profiles written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
