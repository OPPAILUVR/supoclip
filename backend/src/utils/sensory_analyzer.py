"""Sensory Physics & Computer Vision Analyzer for SupoClip.

Extracts objective physical and acoustic signals from video frames and audio streams:
1. Frame-0 Motion Vector Score (Farneback Optical Flow on first 1.5 seconds)
2. Facial Expression & Emotional Intensity (Haar Face & Mouth Dynamics)
3. Acoustic Spectral Flux & Decibel Jump (RMS energy & frequency dynamics)
"""

import os
import subprocess
import tempfile
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional

CASCADE_DIR = cv2.data.haarcascades
FACE_CASCADE = cv2.CascadeClassifier(os.path.join(CASCADE_DIR, "haarcascade_frontalface_default.xml"))
SMILE_CASCADE = cv2.CascadeClassifier(os.path.join(CASCADE_DIR, "haarcascade_smile.xml"))


class SensoryAnalyzer:
    """Analyzes objective physical, visual, and acoustic signals for Shorts virality."""

    @staticmethod
    def compute_frame0_motion_score(
        video_path: str,
        start_s: float = 0.0,
        duration: float = 1.5,
        target_fps: int = 30,
    ) -> float:
        """Calculates optical flow motion vector magnitude across the first 1.5 seconds (frames 0-45).
        
        High score (70-100): High kinetic movement (slamming desk, jumping, camera shake, rapid action).
        Low score (0-35): Passive, motionless, streamer idle, dead air.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 50.0  # Fallback neutral score

        cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        ret, prev_frame = cap.read()
        if not ret or prev_frame is None:
            cap.release()
            return 50.0

        # Downscale for rapid processing and noise rejection
        h, w = prev_frame.shape[:2]
        scale = min(1.0, 360.0 / max(1, h))
        new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
        prev_gray = cv2.cvtColor(cv2.resize(prev_frame, (new_w, new_h)), cv2.COLOR_BGR2GRAY)

        max_frames = int(duration * target_fps)
        magnitudes = []

        frame_count = 0
        while frame_count < max_frames:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            gray = cv2.cvtColor(cv2.resize(frame, (new_w, new_h)), cv2.COLOR_BGR2GRAY)
            
            # Farneback Optical Flow
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            # Focus on top 20% most active pixels (foreground motion)
            top_mag = np.percentile(mag, 85)
            magnitudes.append(float(top_mag))

            prev_gray = gray
            frame_count += 1

        cap.release()

        if not magnitudes:
            return 50.0

        # Mean magnitude across the hook window
        avg_mag = float(np.mean(magnitudes))
        # Empirical scaling: magnitude 0 -> 0, magnitude 8.0+ -> 100
        normalized_score = float(np.clip((avg_mag / 6.0) * 100.0, 0.0, 100.0))
        return round(normalized_score, 2)

    @staticmethod
    def detect_facial_emotional_intensity(
        video_path: str,
        start_s: float = 0.0,
        duration: float = 3.0,
    ) -> float:
        """Measures facial expression dynamics and emotional reaction shifts (screaming, shock, laughter)."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 50.0

        cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        face_areas = []
        smile_counts = []
        frame_idx = 0
        max_frames = int(duration * 15)  # Sample at 15 fps

        while frame_idx < max_frames:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            # Process every 2nd frame for speed
            if frame_idx % 2 == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(40, 40))
                if len(faces) > 0:
                    (x, y, w, h) = faces[0]
                    face_roi = gray[y : y + h, x : x + w]
                    face_areas.append(float(w * h))
                    
                    # Detect mouth / smile area inside face ROI
                    smiles = SMILE_CASCADE.detectMultiScale(face_roi, scaleFactor=1.3, minNeighbors=8)
                    smile_counts.append(len(smiles))

            frame_idx += 1

        cap.release()

        if len(face_areas) < 3:
            return 50.0  # Face not clearly detected, return neutral baseline

        # Measure variance in face positioning & area (rapid leaning in, shaking head, jumping back)
        area_variance = float(np.std(face_areas) / max(1.0, np.mean(face_areas)))
        smile_active = float(np.mean(smile_counts)) if smile_counts else 0.0

        # Composite score
        facial_intensity = (area_variance * 150.0) + (smile_active * 25.0)
        return round(float(np.clip(facial_intensity + 40.0, 0.0, 100.0)), 2)

    @staticmethod
    def compute_acoustic_spectral_flux(
        video_or_audio_path: str,
        start_s: float = 0.0,
        duration: float = 3.0,
    ) -> float:
        """Measures acoustic energy surge (dB jump & spectral flux) in opening window using raw PCM audio."""
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
            pcm_path = tmp.name

        try:
            # Extract raw 16-bit 16000Hz mono PCM snippet via ffmpeg
            cmd = [
                "ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration),
                "-i", video_or_audio_path,
                "-f", "s16le", "-ac", "1", "-ar", "16000",
                pcm_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode != 0 or not os.path.exists(pcm_path) or os.path.getsize(pcm_path) < 1000:
                return 50.0

            raw_bytes = open(pcm_path, "rb").read()
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            if len(samples) < 1600:
                return 50.0

            # 50ms window RMS energy
            frame_len = 800  # 50ms at 16kHz
            num_frames = len(samples) // frame_len
            if num_frames < 2:
                return 50.0

            rms = np.array([
                np.sqrt(np.mean(samples[i * frame_len : (i + 1) * frame_len] ** 2) + 1e-9)
                for i in range(num_frames)
            ])

            # Convert to relative dB
            db_curve = 20.0 * np.log10(rms + 1e-9)
            db_peak = float(np.max(db_curve))
            db_ambient = float(np.percentile(db_curve, 25))
            db_surge = max(0.0, db_peak - db_ambient)

            # Spectral flux (rate of spectral change)
            spectrogram = np.abs(np.array([
                np.fft.rfft(samples[i * frame_len : (i + 1) * frame_len])
                for i in range(num_frames)
            ]))
            spectral_diff = np.diff(spectrogram, axis=0)
            flux = float(np.mean(np.maximum(0, spectral_diff)))

            # Scaled score: +18dB surge with high flux reaches 90-100
            score = (db_surge * 3.5) + (flux * 15.0)
            return round(float(np.clip(score, 0.0, 100.0)), 2)
        finally:
            if os.path.exists(pcm_path):
                os.remove(pcm_path)

    @classmethod
    def analyze_sensory_features(
        cls,
        video_path: str,
        start_s: float = 0.0,
        clip_duration: float = 30.0,
    ) -> Dict[str, Any]:
        """Unified multimodal sensory analyzer returning objective physical metrics."""
        motion_score = cls.compute_frame0_motion_score(video_path, start_s=start_s, duration=1.5)
        facial_score = cls.detect_facial_emotional_intensity(video_path, start_s=start_s, duration=3.0)
        acoustic_flux = cls.compute_acoustic_spectral_flux(video_path, start_s=start_s, duration=3.0)

        # Weighted sensory composite (Hook motion 45%, Acoustic surge 35%, Face reaction 20%)
        composite_score = round(
            (motion_score * 0.45) + (acoustic_flux * 0.35) + (facial_score * 0.20),
            2
        )

        # Penalty flag: if motion is < 35 and acoustic is < 30, it is dead air
        is_passive_dead_air = motion_score < 35.0 and acoustic_flux < 30.0

        return {
            "motion_score_first_1_5s": motion_score,
            "facial_reaction_score": facial_score,
            "acoustic_flux_score": acoustic_flux,
            "composite_sensory_score": composite_score,
            "is_passive_dead_air": is_passive_dead_air,
            "sensory_passed": composite_score >= 65.0 and not is_passive_dead_air,
        }
