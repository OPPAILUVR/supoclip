# SupoClip Modular Codebase Map

Quick-lookup guide so every fix goes straight to the exact folder and file without searching the whole codebase.

## Top-Level Separation
- `backend/` — FastAPI server, background workers, video layouts, AI clip pipelines
- `frontend/` — Next.js App Router UI, API proxies, and modular UI components
- `technical/` — Non-code technical docs, audits, checklists, and prompt archives
  - `technical/audits/` — `SYSTEM_AUDIT_LOG.json`, `SYSTEM_MASTER_CHECKLIST.*`, `AGY_SYSTEM_MEMORY.json`
  - `technical/guides/` — `AGENTS.md`, `AGENT_GUIDE.md`, `CLAUDE.md`, `DEPLOY_NOTES.md`, `REFACTORING_GUIDE.md`, `UPLOAD_CHECKLIST.md`
  - `technical/archives/` — Research & prompt history archives
- `research/` — Empirical video/clip studies and reference assets

## Where to Find Things Fast

### 1. Video Layouts (`40/60 Split` vs `Top-Down Blur / Crop`)
- **40/60 Split (`40_60`)**: `backend/src/media/layouts/split_40_60/`
  - `detector.py` — YuNet facecam clustering, side-by-side divider detection, corner detection
  - `filter_builder.py` — FFmpeg filter builders (1080×760 cam + 1080×1160 gameplay, deterministic fallback)
- **Top-Down Blur (`crop`)**: `backend/src/media/layouts/crop_blur/`
  - `filter_builder.py` — Ambient `boxblur=25:5` canvas + centered 88%×98% foreground crop
- **Unified Dispatcher**: `backend/src/media/layouts/__init__.py` (`build_live_clip_layout`)
- *(Compatibility shim kept at `backend/src/media/streamer_layout.py`)*

### 2. Live Clipper Backend (`backend/src/services/live_clipper/`)
- `cookies_and_probe.py` — YouTube cookie sync (`youtube_cookies.json` → `.txt`), URL normalization, `yt-dlp` live probing
- `streamer_repository.py` — Streamer DB CRUD, format toggle, active/pause toggle, full delete (wipes files + DB)
- `buffer_manager.py` — FFmpeg rolling 60s buffer capture, active session registry, 48h disk/DB cleanup
- `context_trimmer.py` — Pre/post-roll sentence boundary snapping (`apply_context_preroll_and_postroll`)
- `subtitles_and_titles.py` — Whisper cache, ASS animated karaoke captions, unique hook title sanitizer
- `moment_evaluator.py` — Gemini Flash virality evaluation, SensoryAnalyzer calibration, rendering, metadata & thumbnails
- `service.py` — `LiveStreamService` facade *(compatibility shim kept at `backend/src/services/live_stream_service.py`)*

### 3. Background Workers (`backend/src/workers/`)
- `live_stream_worker.py` — Polls streamers concurrently, consecutive offline failure guard, active/pause halt guard, triggers clipping
- `youtube_upload_worker.py` — YouTube Studio auto-uploader & scheduler
- `run_workers.py`, `ai_worker.py`, `cron_worker.py`, `tasks.py` — General task queue & cron workers

### 4. Thumbnails & Metadata
- `backend/src/services/thumbnail_generator.py` — High-CTR 9:16 & 16:9 viral thumbnail generator
- `backend/src/utils/video_metadata.py` — Fair-Use descriptions & MP4 metadata stripping/embedding

### 5. Live Clipper Frontend UI (`frontend/src/components/live/`)
- `frontend/src/app/live/page.tsx` — Live page orchestrator
- `frontend/src/components/live/StreamerFormatButtons.tsx` — **40/60 Split vs Top-Down Blur** buttons
- `frontend/src/components/live/StreamerActionButtons.tsx` — **Active/Paused** toggle button & **Delete** button
- `frontend/src/components/live/StreamerStatusBadge.tsx` — `PAUSED` / `LIVE NOW` / `OFFLINE` status pills
- `frontend/src/components/live/StreamerCard.tsx` — Streamer card layout
- `frontend/src/components/live/AddStreamerForm.tsx` — Watch Streamer form & submit button
- `frontend/src/components/live/LiveClipsFeed.tsx` — Generated clips grid, filter/sort toolbar, Download button
- `frontend/src/components/live/live-api.ts` — All `/api/live-streamers/*` client API calls
- `frontend/src/app/api/live-streamers/**` — Next.js authenticated proxy routes to FastAPI (`backend/src/api/routes/live_streamers.py`)
