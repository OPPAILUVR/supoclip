# SYSTEM MASTER CHECKLIST & OPERATIONAL SPECIFICATION
**SupoClip Production Engine — Absolute Ground Truth Rules**
*Last Updated: 2026-11-23 | Audit Cycle: Every 3 Hours*

---

## 1. MANDATORY ATOMIC PRE-FLIGHT RULES (Zero Exceptions)

| # | Check Item | Requirement / Threshold | Failure Action |
|---|---|---|---|
| **1.1** | **Custom Viral Thumbnail** | Generated via OpenCV peak-emotion/climax detection (35%–60% window). Color graded (+25% sat, +15% contrast). Electric Yellow `#FFE600` Impact bold typography with 10px black stroke and drop shadow. Red reaction pill badge. Attached to YouTube Studio and saved. | **BLOCK UPLOAD**. Clip remains strictly local. |
| **1.2** | **Full High-CTR Description** | Must be $>50$ characters. Must include: 1) Punchy hook curiosity text, 2) Streamer attribution (`🎮 Featured Streamer:`), 3) Original stream URL, 4) Section 107 Copyright Fair Use disclaimer, 5) Hashtags (`#shorts`, streamer tags, niche tags). | **BLOCK UPLOAD**. Clip remains strictly local. |
| **1.3** | **Content-Grounded Title** | Must describe specific on-screen action (Who + What happened). Zero generic clickbait. Must end with `#shorts`. Must be unique in the database. | **BLOCK UPLOAD**. Regenerate title. |
| **1.4** | **Frame-0 Inverted Hook** | First 1.5s (0–45 frames) MUST contain peak visual action or emotional explosion. Absolute ban on 5–15s dead-air pre-rolls or silent introductions. | **RE-RENDER**. Trim dead-air to frame 0. |
| **1.5** | **Zero Drafts Policy** | Videos MUST publish directly to `Public`. If a video lands in `Draft`, the uploader must immediately publish it or permanently delete it within the same session. Zero drafts permitted in YouTube Studio. | **AUTO-PURGE**. Delete draft immediately. |
| **1.6** | **Audio & Video Integrity** | File must have valid moov atom, active H.264 video stream, active AAC audio stream (zero-audio clips strictly banned), duration 30.0s to 59.9s (vertical 9:16). | **BLOCK UPLOAD**. Demux inspection failure. |

---

## 2. MULTI-STREAMER FAIR DISPATCH & CADENCE RULES

| Virality Tier | Streamer Scenario | Cooldown Gap | Daily Cap | Dispatch Priority |
|---|---|---|---|---|
| **Tier 1: Unicorn ($\ge 98$)** | Any Streamer | Instant (0–1 min) | **Bypasses daily caps** | Absolute top priority. Preempts all queues. |
| **Tier 2: Ultra-Viral ($\ge 95$)** | Multiple Streamers Active | 3–4 minutes | **Max 2 clips/day per streamer** | Alternating interleaving (fair-share round-robin). |
| **Tier 2: Ultra-Viral ($\ge 95$)** | Solo Streamer Active (others offline) | 3–4 minutes | **Up to 5 clips/day** | Solo-streamer spillover (unlocked up to 5/day). |
| **Tier 3: Standard ($< 95$)** | Any Streamer | 50–100 minutes | Remaining daily quota | Strategic prime windows (morning, midday, evening, night). |

---

## 3. SENSORY PHYSICS & VIRALITY SCORING MATRIX

- **Optical Flow Motion Vector (Frames 0–45)**: Measures pixel velocity in first 1.5s. Low motion caps hook score at 10/25.
- **Facial Shock & Landmark Variance**: Detects mouth-open percentage, eyebrow elevation, and sudden head tilts to identify genuine scream/rage/laughter peaks.
- **Acoustic Spectral Flux**: Detects sudden dynamic range shifts ($+15$ to $+25\text{ dB}$ bursts) above ambient stream noise floor.
- **Ronald Unscripted Benchmarks**: Calibrated against 500 top-performing clips ($\ge 1\text{M}$ views) targeting $>80\%$ Stayed to Watch and $>90\%$ Average Percentage Viewed (AVD).

---

## 4. STORAGE & RESOURCE MANAGEMENT

- **Hard Ceiling**: 10.0 GB maximum media storage across buffers, clips, and cache.
- **Eviction Threshold**: Triggers automatically at 6.0 GB.
- **Eviction Hierarchy**: FIFO deletion of oldest buffer chunks and local clips until storage drops safely below 6.0 GB, guaranteeing at least 4.0 GB free disk space at all times.

---

## 5. AUTOMATED 3-HOUR SELF-AUDITING WATCHDOG

The watchdog worker executes every 3 hours (180 minutes) to verify:
1. **YouTube Studio Live Audit**: Verifies 0 drafts exist on YouTube Studio (auto-deletes any rogue drafts).
2. **Thumbnail Verification**: Verifies every video uploaded has an active custom viral thumbnail.
3. **Description Verification**: Verifies every video has full metadata, attribution, and hashtags.
4. **Worker Heartbeat**: Verifies `live_stream_worker` and `youtube_upload_worker` are active.
5. **Storage Check**: Confirms total disk footprint is $<10\text{ GB}$.
6. **Audit Trail**: Logs results to `SYSTEM_AUDIT_LOG.json` and synchronizes with `AGY_SYSTEM_MEMORY.json`.
