# SupoClip — Autonomous AI Live Stream Clipper & YouTube Shorts Engine

SupoClip is a fully autonomous open-source AI video clipping and automated YouTube Shorts publishing platform. It monitors live streams 24/7 across Kick, Twitch, and YouTube, records rolling video buffers, detects peak entertaining and viral moments using multimodal AI and Whisper transcription, reframes landscape gameplay/facecam streams into vertical 9:16 Shorts with ambient blurred canvases and dynamic animated subtitles, and autonomously publishes them to YouTube with anti-bot and anti-shadowban pacing.

---

## Architecture Overview

```
                                      +--------------------------+
                                      | Next.js Frontend (3107)  |
                                      | - Dashboard (/live)      |
                                      +------------+-------------+
                                                   | REST / SSE
                                                   v
+------------------------+            +--------------------------+
|  Kick / Twitch / YT    |  yt-dlp    |   FastAPI Backend (8000) |
|      Live Streams      +----------->|   - Streamer Management  |
+------------------------+            |   - PostgreSQL Storage   |
                                      +------------+-------------+
                                                   |
                   +-------------------------------+-------------------------------+
                   |                                                               |
                   v                                                               v
+---------------------------------------+                       +---------------------------------------+
|    live_stream_worker (Daemon)        |                       |    youtube_auto_scheduler (Daemon)    |
| - 10-Minute Rolling Buffers           |                       | - Prioritized 95+ Viral Uploads       |
| - 10 GB Global Disk Ceiling           |                       | - 3 to 5 Min Anti-Bot Cooldown        |
| - Whisper Audio Transcription         |                       | - 100-145 Min Anti-Shadowban Pacing   |
| - AI Virality & Hook Scoring          |                       | - 100% Unique High-CTR Titles         |
| - 6% Horizontal / 1% Vertical Crop    |                       | - Headless Playwright YouTube Studio  |
| - 1080x1920 Ambient Blurred Canvas    |                       | - Automated 2FA / Reauth Handler      |
| - Dynamic ASS Subtitles & Pop Hooks   |                       +---------------------------------------+
+---------------------------------------+
```

---

## Core Features & Configuration

### 1. Rolling Buffer & Disk Retention Policy
* **Streamer Buffer Window**: Retains a rolling **10-minute buffer** per active streamer.
* **Global Disk Quota**: Capped at **10 GB** across all streamer buffers. When the total directory size exceeds 10 GB, older chunk files (`chunk_*.mp4`) are automatically pruned via FIFO cleanup.

### 2. Streamer Crop & Reframing Geometry
Configured in `backend/src/services/live_stream_service.py`:
* **Aspect Ratio**: 1080×1920 (9:16 vertical Shorts format).
* **Ambient Background**: Source stream scaled to fill 1080×1920 and blurred (`boxblur=25:5`).
* **Foreground Crop**:
  * **Horizontal**: 6% cropped from left, 6% cropped from right (12% total width cropped).  
    Width: `trunc(iw*0.88/2)*2`, Left offset: `trunc(iw*0.06/2)*2`
  * **Vertical**: 1% cropped from top, 1% cropped from bottom (2% total height cropped).  
    Height: `trunc(ih*0.98/2)*2`, Top offset: `trunc(ih*0.01/2)*2`
  * **FFmpeg Filtergraph**:
    ```bash
    [0:v]split=2[bgsrc][fgsrc];\
    [bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];\
    [fgsrc]crop=trunc(iw*0.88/2)*2:trunc(ih*0.98/2)*2:trunc(iw*0.06/2)*2:trunc(ih*0.01/2)*2,scale=1080:1920:force_original_aspect_ratio=decrease[fg];\
    [bg][fg]overlay=(W-w)/2:(H-h)/2[vout]
    ```

### 3. Subtitles & Hook Title Styling
* Built using styled Advanced SubStation Alpha (`.ass`):
  * **Top Hook Title**: Pop spring entrance (`\t(0,250,\fscx100\fscy100)`), holds for 8s with electric yellow highlights (`\c&H0000FFFF&`) on viral trigger words (*MISTAKE, REGRET, CAUGHT, 4K, UNHINGED, RUINED, FAILED*).
  * **Dynamic Captions**: Positioned at bottom center (`MarginV=384`, `caption_y=0.80`), rendered with bold outline and soft shadow for high contrast over gameplay.

### 4. YouTube Publishing & Anti-Bot Protection
Configured in `backend/src/services/youtube_auto_scheduler.py` & `backend/src/services/youtube_headless_uploader.py`:
* **Ultra-Viral Clips (Score $\ge$ 95)**:
  * Prioritized for immediate upload.
  * **Mandatory Cooldown**: Enforces a randomized **3 to 5 minute (180–300s)** delay between uploads to prevent rapid bot-like bursts that flag YouTube's anti-spam heuristics.
* **Standard Clips (Score < 95)**:
  * Scheduled on an intelligent cadence of **100 to 145 minutes** to prevent algorithmic shadowbanning.
* **100% Unique Titles**:
  * Cross-checked against all historical titles in PostgreSQL (`generated_clips`).
  * If a generic or repetitive title is detected, Gemini generates a bespoke 3-to-7 word curiosity-gap title derived from the live transcript.
* **Metadata & Takedown Notice**:
  * Default removal email: `luv5668tyagi@gmail.com`.
  * Automatic FFmpeg stripping of previous encoder metadata and embedding of clean SEO tags and streamer credits.

---

## Repository Structure

```
.
├── AGENT_GUIDE.md                      # This comprehensive agent guide
├── docs/research/                      # Viral clipping & streamer reframing research
│   ├── cutting_skill_mastery_and_transcript_analysis.md
│   ├── instant_viral_youtube_upload_engine.md
│   ├── master_multimodal_viral_synthesis.md
│   ├── this_week_trending_clipper_study.md
│   ├── universal_multimodal_virality_matrix.md
│   └── viral_clipper_master_study.md
├── backend/
│   ├── src/
│   │   ├── services/
│   │   │   ├── live_stream_service.py       # Core buffer, render & crop engine
│   │   │   ├── youtube_auto_scheduler.py    # Autonomous upload scheduler & cooldown
│   │   │   ├── youtube_headless_uploader.py # Headless Playwright YouTube Studio uploader
│   │   │   └── video_service.py
│   │   ├── workers/
│   │   │   └── live_stream_worker.py        # 24/7 multi-platform stream recorder
│   │   ├── utils/
│   │   │   ├── video_metadata.py            # Unique titles, SEO descriptions, takedown email
│   │   │   └── motion_analyzer.py           # Action & motion detection
│   │   └── media/
│   │       └── streamer_layout.py           # Facecam & layout detection
│   └── scripts/
│       └── setup_youtube_auth.py            # One-time YouTube Studio authentication utility
└── frontend/
    └── src/app/live/page.tsx                # SupoClip Live Streamer & Clip Management Dashboard
```

---

## How to Run SupoClip

### 1. Database
```bash
# Ensure PostgreSQL is running on localhost:5432
createdb supoclip
```

### 2. Backend API
```bash
cd backend
source .venv/bin/activate
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend Dashboard
```bash
cd frontend
pnpm dev --port 3107
# Dashboard available at: http://localhost:3107/live
```

### 4. Background Workers (Daemons)
```bash
cd backend
source .venv/bin/activate

# Start 24/7 Live Stream Recorder & Clipper
PYTHONPATH=. python -m src.workers.live_stream_worker >> live_stream_worker.log 2>&1 &

# Start Autonomous YouTube Uploader & Cooldown Scheduler
PYTHONPATH=. python src/services/youtube_auto_scheduler.py >> youtube_scheduler_daemon.log 2>&1 &
```
