# SYSTEM MASTER CHECKLIST & OPERATIONAL SPECIFICATION
**SupoClip Production Engine — Absolute Ground Truth Rules**
*Last Updated: 2026-11-24 | Audit Cycle: Every 3 Hours*

---

## 1. MANDATORY ATOMIC PRE-FLIGHT RULES (Zero Exceptions)

| # | Check Item | Requirement / Threshold | Failure Action |
|---|---|---|---|
| **1.1** | **Custom Viral Thumbnail** | Generated via OpenCV peak-emotion/climax detection (35%–60% window). Color graded (+25% sat, +15% contrast). Electric Yellow `#FFE600` Impact bold typography with 10px black stroke and drop shadow. Red reaction pill badge. Attached to YouTube Studio and saved. | **BLOCK UPLOAD**. Clip remains strictly local. |
| **1.2** | **Full High-CTR Description** | Must be $>50$ characters. Must include: 1) Punchy hook curiosity text, 2) Streamer attribution (`🎮 Featured Streamer:`), 3) Original stream URL, 4) Section 107 Copyright Fair Use disclaimer, 5) Hashtags (`#shorts`, streamer tags, niche tags). | **BLOCK UPLOAD**. Clip remains strictly local. |
| **1.3** | **Content-Grounded Title** | Must describe specific on-screen action (Who + What happened). Zero generic clickbait. Must end with `#shorts`. Must be unique in the database. | **BLOCK UPLOAD**. Regenerate title. |
| **1.4** | **Frame-0 Inverted Hook** | First 1.5s (0–45 frames) MUST contain peak visual action or emotional explosion. Absolute ban on 5–15s dead-air pre-rolls or silent introductions. | **RE-RENDER**. Trim dead-air to frame 0. |
| **1.5** | **Zero Drafts Policy** | Videos MUST publish directly to `Public`. If a video lands in `Draft`, the uploader must immediately publish it or permanently delete it within the same session. Zero drafts permitted in YouTube Studio. | **AUTO-PURGE**. Delete draft immediately. |
| **1.6** | **Audio & Video Integrity** | File must have valid moov atom, active H.264 video stream, active AAC audio stream (zero-audio clips strictly banned), duration 30.0s to 175.0s (vertical 9:16). | **BLOCK UPLOAD**. Demux inspection failure. |

---

## 2. FORMAT STANDARDS & USER SELECTION

- **Dual Embedded Formats (Configurable Per Streamer)**:
  1. **40/60 Split (`40_60`)**: Facecam Top 40% ($1080 \times 760\text{px}$, Lanczos + unsharp 0.6) + Gameplay Bottom 60% ($1080 \times 1160\text{px}$, Lanczos), zero gap seamless vstack. Subtitle position $Y = 0.85$.
  2. **Top-Down Blur (`crop`)**: Centered 16:9 stream overlay with 6% horizontal and 1% vertical edge crop over ambient blurred background canvas ($1080 \times 1920\text{px}$, `boxblur=25:5`). Subtitle position $Y = 0.80$.
- **Dynamic Context Duration**: Strict minimum 30.0s, dynamically extending up to 175.0s to capture complete narrative context, rants, debates, and punchlines without premature cuts.

---

## 3. 2-2-2 PEAK VIRALITY SLOT DISPATCH SCHEDULE

Optimized specifically for US & Canada audiences (EST timezone):

| Slot | Time Window (EST) | Target Uploads | Spacing | Selection Rule |
|---|---|---|---|---|
| **Slot 1 (Early Morning)** | 05:30 – 07:00 EST | 2 videos | ~35 minutes apart | Highest calibrated virality score |
| **Slot 2 (Midday / Lunch)** | 13:00 – 14:30 EST | 2 videos | ~35 minutes apart | Highest calibrated virality score |
| **Slot 3 (Prime Night)** | 22:00 – 23:30 EST | 2 videos | ~35 minutes apart | Highest calibrated virality score |

Total: **6 standout videos per day**, interleaving streamers to prevent audience fatigue.

---

## 4. STORAGE & RETENTION SPECIFICATION

- **Ceiling**: 10.0 GB maximum media storage.
- **Retention Policy**: Automatic 48-hour expiration for completed clips and associated database events.
- **Buffer Management**: Rolling buffer keeps 20 chunks (60s each, ~20 minutes) during live broadcast; excess chunks purged continuously.

---

## 5. AUTOMATED 3-HOUR SELF-AUDITING WATCHDOG

The watchdog worker executes every 3 hours (180 minutes) to verify:
1. **YouTube Studio Live Audit**: Verifies 0 drafts exist on YouTube Studio (auto-deletes any rogue drafts).
2. **Thumbnail Verification**: Verifies every video uploaded has an active custom viral thumbnail.
3. **Description Verification**: Verifies every video has full metadata, attribution, and hashtags.
4. **Worker Heartbeat**: Verifies `live_stream_worker` and `youtube_upload_worker` are active.
5. **Storage Check**: Confirms total disk footprint is $<10\text{ GB}$ and prunes items older than 48 hours.
6. **Audit Trail**: Logs results to `SYSTEM_AUDIT_LOG.json` and synchronizes with `AGY_SYSTEM_MEMORY.json`.
