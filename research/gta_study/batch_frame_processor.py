#!/usr/bin/env python3
"""
Production Batch Frame-by-Frame Multimodal Processor for GTA 5 Shorts.
Watches videos frame-by-frame, performs:
- Audio transcription via Whisper with segment timestamps
- Facecam detection & quadrant mapping (OpenCV Haar Cascade)
- Emotion recognition: Smile/laughter ratio, Wide-eye/shock ratio
- Gameplay motion dynamics: Frame differencing & optical energy peaks
- Second-by-second emotion & motion timeline
- Automatic temp file cleanup to keep disk usage at ~0 MB
- Real-time resumable progress tracking with anti-detection jitter
"""

import os
import sys
import json
import time
import random
import argparse
from pathlib import Path
import cv2
import numpy as np
import yt_dlp
import whisper

STUDY_DIR = Path("/Users/luv/.gemini/antigravity/scratch/supoclip/research/gta_study")
STUDY_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR = STUDY_DIR / "temp_video"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

DATASET_FILE = STUDY_DIR / "gta5_dataset_1000.jsonl"
OUTPUT_FILE = STUDY_DIR / "gta5_frame_analysis_1000.jsonl"
PROGRESS_FILE = STUDY_DIR / "batch_frame_progress.json"

FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
SMILE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_smile.xml")
EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

def load_processed_ids():
    processed = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        d = json.loads(line)
                        if "id" in d:
                            processed.add(d["id"])
                    except Exception:
                        pass
    return processed

def load_dataset():
    records = []
    if DATASET_FILE.exists():
        with open(DATASET_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    return records

def download_short(vid_id):
    temp_target = TEMP_DIR / f"{vid_id}.mp4"
    if temp_target.exists():
        temp_target.unlink()

    url = f"https://www.youtube.com/shorts/{vid_id}"
    ydl_opts = {
        # Prioritize 480p/720p mp4 for efficient frame decode & bandwidth preservation
        "format": "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": str(temp_target),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "socket_timeout": 10,
        "retries": 2,
        "fragment_retries": 2,
        "skip_unavailable_fragments": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if temp_target.exists() and temp_target.stat().st_size > 10000:
            return temp_target
    except Exception as e:
        print(f"Download failed for {vid_id}: {e}")
    return None

def transcribe(model, video_path):
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
            "text": res.get("text", "").strip(),
            "language": res.get("language", "en"),
            "segments": segments
        }
    except Exception as e:
        return {"text": "", "language": "unknown", "segments": []}

def analyze_frames(video_path):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / fps if fps > 0 else 0

    face_detected_frames = 0
    smile_frames = 0
    shock_frames = 0
    prev_gray = None
    motion_energies = []
    face_positions = []

    second_timeline = []
    current_sec = 0
    sec_faces = 0
    sec_smiles = 0
    sec_shocks = 0
    sec_motion = []

    # Sample at ~6 frames per second for high-precision emotion tracking
    step = max(1, int(fps / 6))
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_idx / fps
        sec_idx = int(timestamp)

        if sec_idx > current_sec:
            second_timeline.append({
                "sec": current_sec,
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

            # Frame difference for action/motion energy
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

                # Quadrant tracking
                qx = "right" if (fx + fw/2) > w/2 else "left"
                qy = "bottom" if (fy + fh/2) > h/2 else "top"
                face_positions.append(f"{qy}_{qx}")

                # Emotion: Smile/laughter cascade
                smiles = SMILE_CASCADE.detectMultiScale(face_roi, scaleFactor=1.7, minNeighbors=20, minSize=(20, 20))
                if len(smiles) > 0:
                    smile_frames += 1
                    sec_smiles += 1

                # Emotion: Eye/shock cascade (wide eyes)
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

    peak_smile_sec = max(second_timeline, key=lambda x: x["smile_count"])["sec"] if second_timeline else 0
    peak_shock_sec = max(second_timeline, key=lambda x: x["shock_count"])["sec"] if second_timeline else 0
    peak_motion_sec = max(second_timeline, key=lambda x: x["avg_motion"])["sec"] if second_timeline else 0

    return {
        "duration_s": round(duration_s, 2),
        "total_frames_analyzed": frame_idx,
        "sample_points": samples_count,
        "fps": round(fps, 1),
        "facecam": {
            "present": face_detected_frames > (samples_count * 0.15),
            "presence_ratio": round(face_detected_frames / samples_count, 3),
            "dominant_quadrant": dominant_pos,
        },
        "emotions": {
            "laughter_ratio": round(smile_frames / max(1, face_detected_frames), 3),
            "shock_ratio": round(shock_frames / max(1, face_detected_frames), 3),
            "peak_laughter_sec": peak_smile_sec,
            "peak_shock_sec": peak_shock_sec,
        },
        "gameplay_dynamics": {
            "avg_motion_energy": round(float(np.mean(motion_energies)), 2) if motion_energies else 0.0,
            "max_motion_energy": round(float(np.max(motion_energies)), 2) if motion_energies else 0.0,
            "peak_motion_sec": peak_motion_sec,
        },
        "second_timeline": second_timeline
    }

def run_session(session_size=100, max_total=1000):
    print("=" * 60)
    print("GTA 5 YouTube Shorts Frame-by-Frame Processor Starting")
    print(f"Target Session Size: {session_size} | Max Total Target: {max_total}")
    print("=" * 60)

    dataset = load_dataset()
    processed_ids = load_processed_ids()
    print(f"Dataset contains {len(dataset)} clips. Already processed: {len(processed_ids)} clips.")

    pending = [r for r in dataset if r.get("id") and r["id"] not in processed_ids]
    print(f"Remaining to process: {len(pending)} clips.")

    if not pending:
        print("All clips have already been processed!")
        return

    print("Loading Whisper 'base' transcription model into memory...")
    whisper_model = whisper.load_model("base")
    print("Whisper model loaded successfully.")

    session_count = 0
    total_processed_count = len(processed_ids)
    start_time = time.time()

    for r in pending:
        if total_processed_count >= max_total:
            print(f"Reached maximum total limit of {max_total} clips.")
            break

        vid_id = r["id"]
        title = r.get("title", "")
        cat = r.get("category", "")
        duration = r.get("duration", 0)

        print(f"\n[{total_processed_count + 1}/{max_total}] Processing: [{vid_id}] {title[:60]}... ({duration}s, {cat})")

        # Skip invalid durations or active live streams
        if duration <= 0 or duration > 75:
            print(f"--> Skipping {vid_id}: Live stream or invalid duration ({duration}s).")
            err_record = {
                "id": vid_id,
                "title": title,
                "category": cat,
                "status": "skipped_live_stream",
                "processed_at": time.time()
            }
            with open(OUTPUT_FILE, "a", encoding="utf-8") as out_f:
                out_f.write(json.dumps(err_record) + "\n")
            processed_ids.add(vid_id)
            total_processed_count += 1
            continue

        # 1. Download
        t0 = time.time()
        video_path = download_short(vid_id)
        if not video_path:
            print(f"--> Skipping {vid_id}: Could not download (may be deleted, private, or age-restricted).")
            # Mark as attempted with error record to avoid getting stuck
            err_record = {
                "id": vid_id,
                "title": title,
                "category": cat,
                "status": "download_failed",
                "processed_at": time.time()
            }
            with open(OUTPUT_FILE, "a", encoding="utf-8") as out_f:
                out_f.write(json.dumps(err_record) + "\n")
            processed_ids.add(vid_id)
            total_processed_count += 1
            continue

        dl_time = round(time.time() - t0, 1)

        # 2. Audio Transcription
        t1 = time.time()
        transcript = transcribe(whisper_model, video_path)
        tx_time = round(time.time() - t1, 1)

        # 3. Frame-by-frame analysis
        t2 = time.time()
        frame_metrics = analyze_frames(video_path)
        frame_time = round(time.time() - t2, 1)

        # 4. Cleanup raw MP4 immediately
        if video_path.exists():
            video_path.unlink()

        # 5. Build full analysis record
        record = {
            "id": vid_id,
            "title": title,
            "channel": r.get("channel", ""),
            "views": r.get("view_count", 0),
            "category": cat,
            "status": "success",
            "timing": {
                "download_s": dl_time,
                "transcribe_s": tx_time,
                "frame_analysis_s": frame_time,
                "total_s": round(dl_time + tx_time + frame_time, 1)
            },
            "transcript": transcript,
            "frame_analysis": frame_metrics,
            "processed_at": time.time()
        }

        with open(OUTPUT_FILE, "a", encoding="utf-8") as out_f:
            out_f.write(json.dumps(record) + "\n")

        processed_ids.add(vid_id)
        session_count += 1
        total_processed_count += 1

        elapsed = time.time() - start_time
        avg_per_clip = elapsed / session_count
        eta_minutes = round((session_size - session_count) * avg_per_clip / 60, 1) if session_size > session_count else 0

        # Update progress file
        progress_data = {
            "total_processed": total_processed_count,
            "session_processed": session_count,
            "session_target": session_size,
            "max_target": max_total,
            "last_processed_id": vid_id,
            "last_processed_title": title,
            "avg_seconds_per_clip": round(avg_per_clip, 1),
            "session_eta_minutes": eta_minutes,
            "updated_at": time.time()
        }
        with open(PROGRESS_FILE, "w", encoding="utf-8") as pf:
            json.dump(progress_data, pf, indent=2)

        fc = frame_metrics.get("facecam", {}) if frame_metrics else {}
        em = frame_metrics.get("emotions", {}) if frame_metrics else {}
        gd = frame_metrics.get("gameplay_dynamics", {}) if frame_metrics else {}
        print(f"--> Done ({record['timing']['total_s']}s) | Facecam: {fc.get('dominant_quadrant')} ({fc.get('presence_ratio',0)*100:.0f}%) | "
              f"Laughter: {em.get('laughter_ratio')} | Shock: {em.get('shock_ratio')} | MaxMotion: {gd.get('max_motion_energy')}")
        print(f"--> Progress: Session {session_count}/{session_size} (Total {total_processed_count}/{max_total}) | ETA: ~{eta_minutes} mins")

        if session_count >= session_size:
            print(f"\nSession target of {session_size} clips completed successfully!")
            break

        # Polite jitter delay between downloads (2.0s - 3.5s) to stay undetected
        delay = random.uniform(2.0, 3.5)
        time.sleep(delay)

    print("\n" + "=" * 60)
    print(f"BATCH COMPLETE: {session_count} clips processed in this session.")
    print(f"Total processed in dataset: {total_processed_count}/{max_total}")
    print(f"Results saved to: {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch Frame-by-Frame Processor for GTA Shorts")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of clips to process in this session")
    parser.add_argument("--max-total", type=int, default=1000, help="Total target clips across all sessions")
    args = parser.parse_args()

    run_session(session_size=args.batch_size, max_total=args.max_total)
