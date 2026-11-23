# SupoClip — YouTube Upload Pre-Flight Checklist

Every clip **must** pass every item below before the upload worker sends it to YouTube.
If any check fails, the clip is **held locally** and the failure is logged. No video touches YouTube until every box can be ticked.

---

## 1. Video File Integrity

- [ ] **File exists on disk** — `file_path` resolves to a real `.mp4` file. If missing, mark `file_not_found` and skip.
- [ ] **File is not empty** — file size > 0 bytes.
- [ ] **Has video stream** — `ffprobe` confirms at least one video track (codec: h264/h265).
- [ ] **Has audio stream** — `ffprobe` confirms at least one audio track (codec: aac/opus). Zero-audio clips must never upload.

## 2. Duration

- [ ] **Minimum 30 seconds** — clip duration ≥ 30.0s. Reject anything shorter.
- [ ] **Context-appropriate length** — duration is determined by the content, not a fixed number. Acceptable range: **30–58 seconds**. Do not rigidly cut every clip at 38 seconds.
- [ ] **Under 60 seconds** — must qualify as a YouTube Short (< 60s).

## 3. Title

- [ ] **Title is not empty** — a non-blank `hook_title` exists.
- [ ] **Title is unique** — no other Public video on the channel already has this exact title. Pre-upload audit checks the YouTube Studio table for duplicates.
- [ ] **Ends with `#shorts`** — append `#shorts` if not already present.
- [ ] **Title is different from other queued clips** — not the same title as any other clip waiting in the upload queue.

## 4. Description

- [ ] **Description is not empty** — `build_viral_youtube_description()` returned a string with length > 50 characters.
- [ ] **Contains streamer attribution** — text includes `🎮 Featured Streamer:` with the correct display name and @handle.
- [ ] **Contains original stream link** — text includes `📺 Watch original stream:` with a valid URL.
- [ ] **Contains fair use disclaimer** — text includes the Section 107 Copyright Act notice and takedown email.
- [ ] **Contains hashtags** — text includes `#shorts` and streamer-specific hashtag at the end.
- [ ] **Description was actually filled in YouTube Studio** — the `#description-textarea #textbox` locator was found, clicked, and `.fill()` succeeded. If the locator returns 0 elements, **abort the upload** and log an error — do not silently skip.

## 5. Thumbnail

- [ ] **Thumbnail was generated** — `generate_viral_thumbnail()` produced a `.jpg` file that exists on disk.
- [ ] **Thumbnail was attached** — the `input[type='file'][accept*='image']` element was found and `.set_input_files()` was called. Log whether attachment succeeded or fell back to file chooser.

## 6. Allowed Streamers

- [ ] **Streamer is on the approved list** — the clip's `workflow_meta.streamer` matches one of: `ishowspeed`, `asmong`, `kai`, `botez`. If the streamer is `xqc`, `jynxzi`, or `adinross` (or any other name not on the list), **reject the clip** and do not upload.

## 7. Visibility & Draft Prevention

- [ ] **Visibility set to Public** — the `Public` radio button was clicked in the YouTube Studio upload wizard before hitting Publish.
- [ ] **Post-upload verification** — after clicking Publish, navigate back to the YouTube Studio Shorts table and confirm the video row says `Public` (not `Draft`).
- [ ] **If Draft detected** — immediately attempt to edit the draft to Public. If that also fails, **delete the draft permanently** to maintain zero-draft policy. Never leave a draft sitting on the channel.
- [ ] **On error, discard the upload dialog** — if any exception occurs mid-upload, click "Discard draft" so no orphan draft is created.

## 8. Upload Timing & Queue Discipline

- [ ] **Respect cooldown** — virality ≥ 95: wait 3–4 minutes between uploads. Virality < 95: wait 50–100 minutes.
- [ ] **One at a time** — only one video is being uploaded at any given moment. The next clip stays local until the current upload is fully verified as Public.
- [ ] **Daily limit awareness** — if YouTube returns "Daily upload limit reached", stop all uploads and sleep for 1 hour before retrying. Do not spam retries.

## 9. No Duplicates

- [ ] **Pre-upload channel audit** — before opening the upload dialog, scan the YouTube Studio video table for any row whose title matches this clip. If found as Public, skip (already uploaded). If found as Draft, delete the draft first, then proceed.
- [ ] **DB cross-check** — the clip's `workflow_meta.uploaded` must be `null` or `false`. If `true`, skip.

## 10. Metadata Embedding

- [ ] **ffmpeg metadata strip** — `strip_and_embed_video_metadata()` was called to remove all previous encoder metadata (`-map_metadata -1`) before upload, keeping file headers clean.

---

> **Rule of thumb:** If any single item above cannot be verified as ✅, the clip does **not** go to YouTube. It stays on the local disk, an error is logged with the specific failed check, and the worker moves on to the next clip.
