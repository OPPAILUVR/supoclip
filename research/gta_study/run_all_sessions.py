#!/usr/bin/env python3
"""
Master Session Orchestrator for 1,000 GTA 5 Shorts Frame-by-Frame Study.
Executes 10 distinct sessions of 100 clips each:
- Session 1: Clips 1-100
- Session 2: Clips 101-200
...
- Session 10: Clips 901-1000

Includes:
- Jittered anti-bot delays (2-3.5s per clip)
- Inter-session polite cooldowns (25-35s between sessions)
- Full audio transcription via Whisper
- Full OpenCV frame-by-frame facial emotion and motion analysis
- Immediate temp-file disk wipe
- Automatic resume capability
"""

import sys
import time
import subprocess
from pathlib import Path

STUDY_DIR = Path("/Users/luv/.gemini/antigravity/scratch/supoclip/research/gta_study")
PYTHON_BIN = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/.venv/bin/python"
PROCESSOR_SCRIPT = STUDY_DIR / "batch_frame_processor.py"
LOG_FILE = STUDY_DIR / "session_orchestrator.log"

SESSION_SIZE = 100
TOTAL_TARGET = 1000

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")

def main():
    log("==================================================================")
    log("Starting Master Session Orchestrator (1,000 Clips Frame-by-Frame)")
    log(f"Session Chunk Size: {SESSION_SIZE} clips | Total Target: {TOTAL_TARGET}")
    log("==================================================================")

    session_num = 1
    while True:
        log(f"\n>>> Launching Session {session_num} (Batch size: {SESSION_SIZE})...")

        cmd = [
            PYTHON_BIN,
            str(PROCESSOR_SCRIPT),
            "--batch-size", str(SESSION_SIZE),
            "--max-total", str(TOTAL_TARGET)
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        with proc.stdout:
            for line in proc.stdout:
                line_str = line.rstrip()
                if line_str:
                    log(f"[Worker] {line_str}")

        rc = proc.wait()
        log(f">>> Session {session_num} finished with exit code {rc}")

        # Check total processed count from progress file or output file
        output_file = STUDY_DIR / "gta5_frame_analysis_1000.jsonl"
        processed_count = 0
        if output_file.exists():
            with open(output_file, "r") as f:
                processed_count = sum(1 for l in f if l.strip())

        log(f">>> Current Total Verified Processed Clips: {processed_count}/{TOTAL_TARGET}")

        if processed_count >= TOTAL_TARGET:
            log("==================================================================")
            log("ALL 1,000 GTA 5 SHORTS PROCESSED FRAME-BY-FRAME SUCCESSFULLY!")
            log("==================================================================")
            break

        session_num += 1
        cooldown_sec = 25
        log(f"Polite inter-session anti-detection cooldown: Resting for {cooldown_sec} seconds before next session...")
        time.sleep(cooldown_sec)

if __name__ == "__main__":
    main()
