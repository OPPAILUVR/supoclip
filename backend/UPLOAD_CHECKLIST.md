# SupoClip — YouTube Upload Pre-Flight Checklist
**Current Operational Specification (Version 2.5.0)**

Every clip **must** pass every item below before the upload worker sends it to YouTube.
If any check fails, the clip is **held locally** and the failure is logged. No video touches YouTube until every box is verified.

---

## 1. Video File Integrity & Format

- [ ] **File exists on disk** — `file_path` resolves to a real `.mp4` file. If missing, mark `file_not_found` and skip.
- [ ] **File is not empty** — file size > 0 bytes.
- [ ] **Has video stream** — `ffprobe` confirms at least one video track (codec: h264/h265).
- [ ] **Has audio stream** — `ffprobe` confirms at least one audio track (codec: aac/opus). Zero-audio clips must never upload.
- [ ] **Correct Streamer Layout Format** — Rendered according to the streamer's configured preference:
  - **`40/60 Split`**: Top 40% facecam (1080x760, Lanczos + unsharp 0.6) + Bottom 60% gameplay (1080x1160, Lanczos) with zero gap.
  - **`Top-Down Blur`**: Centered stream overlay over ambient blurred background canvas (1080x1920, `boxblur=25:5`).

## 2. Duration & Story Context

- [ ] **Minimum 30 seconds** — clip duration ≥ 30.0s. Reject anything shorter.
- [ ] **Context-appropriate length** — duration dynamically adapts to the narrative context. Snaps to sentence boundaries without premature cuts.
- [ ] **Long-format reaction & topic transitions** — story arcs and rants (e.g. Asmongold reaction breakdowns) expand dynamically up to 175.0s to capture setup, reaction, monologue, and punchline.
- [ ] **Under 180 seconds** — strictly within YouTube Shorts 3-minute limit (expanded Oct 2024).

## 3. Title

- [ ] **Title is not empty** — a non-blank `hook_title` exists.
- [ ] **Title is unique** — no other Public video on the channel already has this exact title.
- [ ] **Ends with `#shorts`** — append `#shorts` if not already present.
- [ ] **Bespoke and content-grounded** — generated with curiosity-gap verbs based on actual dialogue. Zero generic template clickbait.

## 4. Description

- [ ] **Description is not empty** — `build_viral_youtube_description()` returned a string with length > 50 characters.
- [ ] **Contains streamer attribution** — text includes `🎮 Featured Streamer:` with the correct display name and @handle.
- [ ] **Contains original stream link** — text includes `📺 Watch original stream:` with a valid URL.
- [ ] **Contains fair use disclaimer** — text includes the Section 107 Copyright Act notice and takedown email.
- [ ] **Contains hashtags** — text includes `#shorts` and streamer-specific hashtags.
- [ ] **Description filled in YouTube Studio** — description text area successfully populated via automated upload session.

## 5. Thumbnail

- [ ] **High-CTR 9:16 Thumbnail generated** — YuNet face-aware peak-emotion climax frame selection, multi-color 3D Impact bold typography, cinematic gradient contrast backing, curved neon attention arrow, red reaction pill badge, strict 1080x1920.
- [ ] **Thumbnail was attached** — uploaded and attached directly to the YouTube Studio video entry.

## 6. Allowed Streamers

- [ ] **Streamer is approved or actively tracked** — streamer matches an active monitored streamer in PostgreSQL `live_streamers` (e.g. `asmong`, `caseoh`, `ishowspeed`, `kai`) or the approved roster.
- [ ] **Blocked streamers rejected** — explicitly blocked/removed streamers (`botez`, `xqc`, `jynxzi`, `adinross`) are rejected.

## 7. Visibility & Draft Prevention

- [ ] **Visibility set to Public** — uploaded and published directly as Public.
- [ ] **Post-upload verification** — confirm the video row status is Public.
- [ ] **Zero Drafts Policy** — if a video remains in Draft, immediately attempt to publish or permanently delete it. Zero drafts permitted in YouTube Studio.
- [ ] **Discard on error** — if an error occurs mid-upload, discard the draft to prevent abandoned drafts.

## 8. Upload Cadence & Schedule

- [ ] **2-2-2 Peak Virality Schedule** (6 videos/day total for US & Canada EST audience):
  - **Slot 1 (Early Morning)**: 05:30 – 07:00 EST (2 videos, ~35 min apart)
  - **Slot 2 (Midday / Lunch)**: 13:00 – 14:30 EST (2 videos, ~35 min apart)
  - **Slot 3 (Prime Night)**: 22:00 – 23:30 EST (2 videos, ~35 min apart)
- [ ] **Selection Rule** — unuploaded clips selected strictly by highest calibrated virality score first, interleaving streamers to prevent audience fatigue.

## 9. No Duplicates

- [ ] **Pre-upload channel audit** — scan YouTube Studio video table for duplicates before uploading.
- [ ] **DB cross-check** — clip `workflow_meta.uploaded` must not be already true.

## 10. Storage & Retention

- [ ] **Storage Ceiling** — maximum 10.0 GB disk footprint.
- [ ] **48-Hour Retention** — clips and database event records older than 48 hours are automatically pruned.
- [ ] **Metadata Embedding** — prior encoder metadata stripped (`-map_metadata -1`) before upload.

---

> **Rule of thumb:** If any single item above cannot be verified as ✅, the clip does **not** go to YouTube. It stays on local disk, an error is logged with the specific failed check, and the worker moves to the next candidate.
