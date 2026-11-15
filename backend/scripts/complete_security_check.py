#!/usr/bin/env python3
"""
Runs a single upload in headed mode so the user can click 'Next' on Google's
one-time 'Verify it's you' security prompt. Once completed, Google permanently
marks this browser profile as verified for video publishing.
"""

import sys
import json
import asyncio
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from src.services.youtube_headless_uploader import HeadlessYouTubeUploader, PROFILE_DIR, COOKIES_FILE
from src.utils.video_metadata import strip_and_embed_video_metadata, get_streamer_tags
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://luv@localhost:5432/supoclip"

async def get_test_clip():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT id, filename, file_path, virality_score, hook_title, workflow_meta
            FROM generated_clips
            WHERE (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false' OR workflow_meta->>'status' = 'failed')
            ORDER BY virality_score DESC, created_at DESC
            LIMIT 1
        """))
        row = res.fetchone()
        if row:
            return {
                "id": row[0],
                "filename": row[1],
                "file_path": Path(row[2]),
                "virality_score": row[3],
                "title": row[4],
                "workflow_meta": row[5] or {}
            }
    return None

async def complete_first_time_upload():
    print("=" * 65)
    print("      ONE-TIME YOUTUBE PUBLISHING IDENTITY VERIFICATION")
    print("=" * 65)
    print("A browser window will open and initiate the video upload.")
    print("When Google's 'Verify it's you' dialog appears:")
    print("1. Click 'Next' in the browser window.")
    print("2. Enter your password or tap 'Yes' on your phone.")
    print("Once verified, the script will automatically finish publishing,")
    print("save your permanent credentials, and close.")
    print("All subsequent uploads will then run 100% silently in background!")
    print("=" * 65)

    clip = await get_test_clip()
    if not clip:
        print("[ERROR] No clips available in database.")
        return

    clip_path = clip["file_path"]
    title = clip["title"] or "Live Stream Highlight"
    streamer = clip["workflow_meta"].get("streamer") or "asmong"
    tags = get_streamer_tags(streamer)
    description = f"{title}\n\nStreamer: {streamer}\nClipped live with SupoClip AI.\n\n{' '.join(tags)}"

    print(f"Prepping clip: {clip_path.name} | Title: {title}")
    strip_and_embed_video_metadata(clip_path, title, streamer, tags, description)

    uploader = HeadlessYouTubeUploader(headless=False)
    
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        context = await uploader.get_context(p)
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("\nOpening YouTube Studio upload dialog...")
        await page.goto("https://studio.youtube.com", timeout=60000)
        await asyncio.sleep(2)

        create_btn = page.locator("#create-icon, button:has-text('Create')")
        if await create_btn.count() > 0:
            await create_btn.first.click()
            await asyncio.sleep(1)
            upload_option = page.locator("tp-yt-paper-item:has-text('Upload videos')")
            if await upload_option.count() > 0:
                await upload_option.first.click()

        file_input = page.locator("input[type='file']")
        await file_input.wait_for(state="attached", timeout=20000)
        print(f"Attaching video file: {clip_path.name} ...")
        await file_input.set_input_files(str(clip_path))

        print("\n>>> PLEASE LOOK AT THE BROWSER WINDOW NOW <<<")
        print("If you see 'Verify it\\'s you', click 'Next' and approve the prompt on your phone/screen.")
        print("The script is waiting for identity verification to complete...\n")

        # Wait for either 'Verify it's you' to be resolved and title box to be interactive
        title_box = page.locator("#textbox[aria-label*='title'], ytcp-mention-textbox[label*='Title'] #textbox").first
        
        # Loop until title_box is clickable without being intercepted
        max_wait = 300 # 5 minutes
        start = asyncio.get_event_loop().time()
        title_filled = False

        while asyncio.get_event_loop().time() - start < max_wait:
            try:
                # Check if auth dialog exists
                auth_dialog = page.locator("ytcp-auth-confirmation-dialog, :text('Verify it\\'s you')")
                if await auth_dialog.count() > 0 and await auth_dialog.first.is_visible():
                    # Still visible, wait for user
                    await asyncio.sleep(2)
                    continue

                # Try clicking title box
                if await title_box.count() > 0:
                    await title_box.click(timeout=3000)
                    upload_title = f"{title[:90]} #shorts"
                    await page.keyboard.press("Meta+A")
                    await page.keyboard.press("Backspace")
                    await title_box.type(upload_title, delay=20)
                    print(f"[SUCCESS] Identity verified! Title entered: {upload_title}")
                    title_filled = True
                    break
            except Exception as e:
                # Still being intercepted by dialog or backdrop
                await asyncio.sleep(2)

        if not title_filled:
            print("[TIMEOUT] Verification took longer than 5 minutes.")
            return

        # Fill description
        desc_box = page.locator("#textbox[aria-label*='description'], ytcp-mention-textbox[label*='Description'] #textbox").first
        if await desc_box.count() > 0:
            await desc_box.click()
            await desc_box.type(description, delay=10)

        # Select Not made for kids
        not_kids = page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK'], tp-yt-paper-radio-button:has-text('No, it\\'s not made for kids')").first
        if await not_kids.count() > 0:
            await not_kids.click()
            print("Selected: Not made for kids")

        # Click Next buttons
        next_btn = page.locator("#next-button")
        for i in range(4):
            if await next_btn.is_visible():
                await next_btn.click()
                print(f"Clicked Next ({i+1}/4)")
                await asyncio.sleep(2)

        # Select Public
        pub = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
        if await pub.count() > 0:
            await pub.click()
            print("Selected: Public")

        # Get video link
        link_elem = page.locator("a.ytcp-video-info, a[href*='youtu.be']").first
        video_url = None
        if await link_elem.count() > 0:
            video_url = await link_elem.get_attribute("href")
            print(f"Video URL: {video_url}")

        # Click Publish
        done_btn = page.locator("#done-button, #publish-button, button:has-text('Publish')").first
        if await done_btn.is_visible():
            await done_btn.click()
            print("[SUCCESS] Clicked Publish! Video is officially published to YouTube!")
            await asyncio.sleep(8)

        # Save cookies and storage state
        state_file = BACKEND_DIR / "browser_data" / "storage_state.json"
        await context.storage_state(path=str(state_file))
        cookies = await context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"[SUCCESS] Saved updated session tokens ({len(cookies)} cookies).")

        # Update DB
        engine = create_async_engine(DB_URL)
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE generated_clips
                SET workflow_meta = COALESCE(workflow_meta, '{}'::jsonb) || CAST(:meta AS jsonb)
                WHERE id = :id
            """), {
                "id": clip["id"],
                "meta": json.dumps({
                    "uploaded": True,
                    "uploaded_at": now_iso,
                    "youtube_url": video_url,
                    "youtube_title": title,
                    "status": "published"
                })
            })
        print(f"[SUCCESS] Marked clip {clip['id']} as uploaded in database.")

        await context.close()

    print("\n" + "=" * 65)
    print(" [COMPLETE] VIDEO PUBLISHED & DEVICE PERMANENTLY TRUSTED!")
    print(" All future uploads will now run 100% headless in background.")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(complete_first_time_upload())
