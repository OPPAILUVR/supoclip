#!/usr/bin/env python3
"""
Interactive Headed Browser for YouTube Verification & Publishing.
Opens an active Chromium window on the Mac screen using the persistent YouTube profile.
Triggers the pending 96-score clip upload so Google's 'Verify it's you' prompt
is displayed directly on screen for the user to approve.
Once verified, publishes the video, saves persistent credentials, and keeps the browser
open for the user to review.
"""

import sys
import os
import json
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timezone

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

PROFILE_DIR = BACKEND_DIR / "browser_data" / "youtube_profile"
COOKIES_FILE = BACKEND_DIR / "browser_data" / "youtube_cookies.json"
STATE_FILE = BACKEND_DIR / "browser_data" / "storage_state.json"
DB_URL = "postgresql+asyncpg://luv@localhost:5432/supoclip"

def bring_to_front():
    try:
        subprocess.run([
            "osascript", "-e",
            'tell application "Google Chrome for Testing" to activate'
        ], check=False)
    except Exception:
        pass

async def get_top_pending_clip():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT id, filename, file_path, virality_score, hook_title, workflow_meta
            FROM generated_clips
            WHERE virality_score >= 95
              AND (workflow_meta->>'uploaded' IS NULL OR workflow_meta->>'uploaded' = 'false' OR workflow_meta->>'status' = 'failed')
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

async def save_session_state(context):
    try:
        await context.storage_state(path=str(STATE_FILE))
        cookies = await context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"[AUTH SYNC] Successfully updated session state ({len(cookies)} cookies saved to disk).")
    except Exception as e:
        print(f"[AUTH SYNC WARNING] Could not save cookies: {e}")

async def run_headed_browser():
    print("=" * 70)
    print("  LAUNCHING HEADED BROWSER ON MAC DISPLAY FOR YOUTUBE VERIFICATION")
    print("=" * 70)
    print("1. An active Chromium window will appear on your screen.")
    print("2. It will navigate to YouTube Studio and initiate the 96-score video upload.")
    print("3. When Google asks 'Verify it\\'s you', complete the challenge on screen:")
    print("   - Enter your Oppo A57 security code, OR")
    print("   - Click 'Try another way' (tap phone prompt on iPhone 16 / SMS / Password).")
    print("4. Once verified, the script publishes the video and saves your credentials.")
    print("5. The browser will remain open for you to verify your channel content.")
    print("=" * 70)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    clip = await get_top_pending_clip()
    if not clip or not clip["file_path"].exists():
        print(f"[NOTICE] No pending 95+ clip file found or file missing. Using fallback or manual mode.")
        clip_path = None
    else:
        clip_path = clip["file_path"]
        print(f"\n[TARGET CLIP] Found: {clip_path.name} | Score: {clip['virality_score']} | Title: {clip['title']}")

    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-infobars",
        "--window-size=1400,900",
    ]

    async with async_playwright() as p:
        print("\nOpening Chromium window...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=args,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        # Inject existing cookies if present
        if COOKIES_FILE.exists():
            try:
                with open(COOKIES_FILE, "r") as f:
                    raw_cookies = json.load(f)
                formatted_cookies = []
                for c in raw_cookies:
                    c_dict = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".youtube.com"),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        c_dict["secure"] = c["secure"]
                    if "httpOnly" in c:
                        c_dict["httpOnly"] = c["httpOnly"]
                    if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
                        c_dict["sameSite"] = c["sameSite"]
                    formatted_cookies.append(c_dict)
                await context.add_cookies(formatted_cookies)
                print(f"[INIT] Loaded {len(formatted_cookies)} pre-existing cookies.")
            except Exception as e:
                print(f"[INIT WARNING] Could not inject cookies: {e}")

        page = context.pages[0] if context.pages else await context.new_page()
        bring_to_front()

        print("Navigating to https://studio.youtube.com ...")
        try:
            await page.goto("https://studio.youtube.com", timeout=60000)
        except Exception as e:
            print(f"[NAV NOTICE] Initial page navigation: {e}")

        bring_to_front()
        await asyncio.sleep(3)

        # Check if on Google login page
        if "accounts.google.com" in page.url:
            print("\n" + "!" * 70)
            print(">>> PLEASE SIGN IN TO YOUR GOOGLE ACCOUNT IN THE BROWSER WINDOW <<<")
            print("!" * 70 + "\n")
            bring_to_front()

        # If clip available, initiate upload
        if clip_path and clip_path.exists():
            print("\nInitiating upload wizard for clip...")
            try:
                # Click Create
                create_btn = page.locator("#create-icon, button:has-text('Create'), #upload-button, [aria-label='Upload videos']").first
                if await create_btn.count() > 0:
                    await create_btn.click()
                    await asyncio.sleep(1)
                    upload_opt = page.locator("tp-yt-paper-item:has-text('Upload videos')").first
                    if await upload_opt.count() > 0:
                        await upload_opt.click()

                # Attach file
                file_input = page.locator("input[type='file']")
                await file_input.wait_for(state="attached", timeout=20000)
                print(f"Attaching video file: {clip_path.name}")
                await file_input.set_input_files(str(clip_path))
                print("Video file attached! Waiting for upload details...")
                await asyncio.sleep(3)

                # Check for Google "Verify it's you" prompt
                auth_confirm_btn = page.locator("#confirm-button, ytcp-auth-confirmation-dialog #confirm-button").first
                has_auth_dialog = await page.locator("ytcp-auth-confirmation-dialog, :text('Verify it\\'s you')").count() > 0

                if has_auth_dialog and await auth_confirm_btn.count() > 0 and await auth_confirm_btn.is_visible():
                    print("\n" + "=" * 70)
                    print(">>> GOOGLE 'VERIFY IT\\'S YOU' DIALOG DETECTED! <<<")
                    print("Opening Google challenge window for you now...")
                    print("=" * 70 + "\n")
                    await auth_confirm_btn.click()
                    bring_to_front()

                print("\n>>> LOOK AT THE BROWSER WINDOW NOW <<<")
                print("If a verification challenge appears, complete it on your device/screen.")
                print("The script is waiting for verification to finish before auto-publishing...\n")

                # Wait for title box to become interactable
                title_box = page.locator("#textbox[aria-label*='title'], ytcp-mention-textbox[label*='Title'] #textbox").first
                verified = False
                wait_start = asyncio.get_event_loop().time()

                while asyncio.get_event_loop().time() - wait_start < 480: # 8 minutes
                    try:
                        # Check if any popup is active
                        if len(context.pages) > 1:
                            bring_to_front()

                        # Check if title box is clickable
                        if await title_box.count() > 0 and await title_box.is_visible():
                            await title_box.click(timeout=2000)
                            verified = True
                            print("[VERIFIED] Identity verification completed successfully!")
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                if verified:
                    # Fill title
                    upload_title = f"{clip['title'][:90]} #shorts"
                    await page.keyboard.press("Meta+A")
                    await page.keyboard.press("Backspace")
                    await title_box.type(upload_title, delay=15)
                    print(f"Title set: {upload_title}")

                    # Load description from manifest if available
                    manifest_file = clip_path.with_suffix(".youtube_upload.json")
                    description = ""
                    if manifest_file.exists():
                        try:
                            with open(manifest_file, "r") as mf:
                                manifest_data = json.load(mf)
                            description = manifest_data.get("description", "")
                        except Exception:
                            pass
                    if not description:
                        description = f"{upload_title}\n\nClipped live with SupoClip AI.\n\n#shorts #viral #clips"

                    desc_box = page.locator("#textbox[aria-label*='description'], ytcp-mention-textbox[label*='Description'] #textbox").first
                    if await desc_box.count() > 0:
                        await desc_box.click()
                        await desc_box.type(description, delay=5)
                        print("Description filled!")

                    # Select Not made for kids
                    not_kids = page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK'], tp-yt-paper-radio-button:has-text('No, it\\'s not made for kids')").first
                    if await not_kids.count() > 0:
                        await not_kids.click()
                        print("Selected: 'No, it\\'s not made for kids'")

                    # Click Next through tabs
                    next_btn = page.locator("#next-button")
                    for step in range(3):
                        if await next_btn.is_visible():
                            await next_btn.click()
                            print(f"Navigated step {step+1}/3")
                            await asyncio.sleep(2)

                    # Select Public
                    pub_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
                    if await pub_radio.count() > 0:
                        await pub_radio.click()
                        print("Selected: Public visibility")

                    # Get video link
                    link_elem = page.locator("a.ytcp-video-info, a[href*='youtu.be']").first
                    video_url = None
                    if await link_elem.count() > 0:
                        video_url = await link_elem.get_attribute("href")
                        print(f"Generated YouTube Short URL: {video_url}")

                    # Click Publish
                    done_btn = page.locator("#done-button, #publish-button, button:has-text('Publish')").first
                    if await done_btn.is_visible():
                        await done_btn.click()
                        print("\n" + "=" * 70)
                        print(">>> [SUCCESS] VIDEO OFFICIALLY PUBLISHED TO YOUTUBE! <<<")
                        print(f"URL: {video_url or 'Published as Short'}")
                        print("=" * 70 + "\n")
                        await asyncio.sleep(5)

                        # Update DB
                        engine = create_async_engine(DB_URL)
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
                                    "youtube_title": upload_title,
                                    "status": "published"
                                })
                            })
                        print(f"[DB SYNC] Marked clip {clip['id']} as uploaded in database.")

                    # Save updated session tokens immediately
                    await save_session_state(context)

            except Exception as upload_err:
                print(f"[INTERACTIVE NOTICE] Upload automation note: {upload_err}")
                print("Browser remains open for you to complete manually!")

        # Keep browser open and alive as long as user keeps it open
        print("\n" + "=" * 70)
        print("  BROWSER IS OPEN AND READY")
        print("  Feel free to inspect your YouTube Studio, check videos, or close when done.")
        print("  Session state will automatically sync to disk every 10 seconds.")
        print("=" * 70)

        bring_to_front()

        try:
            while len(context.pages) > 0 and not page.is_closed():
                await asyncio.sleep(10)
                await save_session_state(context)
        except Exception:
            pass

        print("\nBrowser closed by user. Finalizing session tokens...")
        try:
            await save_session_state(context)
            await context.close()
        except Exception:
            pass

    print("\n[COMPLETE] Browser session ended cleanly.")

if __name__ == "__main__":
    asyncio.run(run_headed_browser())
