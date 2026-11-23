#!/usr/bin/env python3
"""
YouTube Authentication Setup Utility for SupoClip / Antigravity.

Usage:
  # Option 1: Launch an isolated browser window once to sign in manually (takes 30 seconds)
  python scripts/setup_youtube_auth.py --login

  # Option 2: Verify current authentication status
  python scripts/setup_youtube_auth.py --check

  # Option 3: Import exported cookies JSON from Chrome extension
  python scripts/setup_youtube_auth.py --import-cookies /path/to/cookies.json
"""

import sys
import os
import json
import asyncio
import argparse
import subprocess
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from src.services.youtube_headless_uploader import HeadlessYouTubeUploader, PROFILE_DIR, COOKIES_FILE
from playwright.async_api import async_playwright

def bring_to_front():
    try:
        subprocess.run([
            "osascript", "-e",
            'tell application "Google Chrome for Testing" to activate'
        ], check=False)
    except Exception:
        pass

async def interactive_login():
    print("=" * 65)
    print("      SUPOCLIP / ANTIGRAVITY ONE-TIME YOUTUBE SIGN-IN")
    print("=" * 65)
    print("Launching an isolated Chromium window for one-time login...")
    print("1. Log in to your Google / YouTube account in the window.")
    print("2. The script will AUTOMATICALLY detect when you reach YouTube Studio,")
    print("   save all tokens/cookies, and close the window automatically.")
    print("3. From then on, all uploads will run 100% silently in the background!")
    print("=" * 65)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars"
            ]
        )
        bring_to_front()
        
        # Get or create page
        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        
        print("Navigating to https://studio.youtube.com ...")
        bring_to_front()
        try:
            await page.goto("https://studio.youtube.com", timeout=60000)
        except Exception as e:
            print(f"Initial navigation notice: {e}")

        print("\nWaiting for you to complete sign-in in the browser window...")
        print("(Auto-detecting login progress every 2 seconds for up to 10 minutes...)\n")

        logged_in = False
        start_time = asyncio.get_event_loop().time()
        max_wait_seconds = 600  # 10 minutes

        while asyncio.get_event_loop().time() - start_time < max_wait_seconds:
            try:
                if context.pages and not page.is_closed():
                    current_url = page.url
                    # Check if user reached studio.youtube.com and is not on Google accounts/signin
                    if "studio.youtube.com" in current_url and "accounts.google.com" not in current_url:
                        # Extra verification: wait for studio dashboard content or title
                        title = await page.title()
                        if "channel" in current_url or "dashboard" in current_url or "Studio" in title or "YouTube" in title:
                            print(f"[SUCCESS] Login detected! Current URL: {current_url} | Title: {title}")
                            logged_in = True
                            await asyncio.sleep(3) # Wait 3s for session cookies to settle
                            break
                else:
                    print("Browser window was closed by user.")
                    break
            except Exception as e:
                # Handle possible window close or context disconnect
                if "Target page, context or browser has been closed" in str(e):
                    print("Browser window closed.")
                    break
            await asyncio.sleep(2)

        # Save cookies and persistent storage state
        state_file = BACKEND_DIR / "browser_data" / "storage_state.json"
        try:
            await context.storage_state(path=str(state_file))
            print(f"[SUCCESS] Saved persistent storage state to: {state_file}")
            
            # Also extract and save raw cookies for backup
            cookies = await context.cookies()
            with open(COOKIES_FILE, "w") as f:
                json.dump(cookies, f, indent=2)
            print(f"[SUCCESS] Exported {len(cookies)} cookies to: {COOKIES_FILE}")
        except Exception as e:
            print(f"Notice saving state: {e}")

        try:
            await context.close()
        except Exception:
            pass

    if logged_in:
        print("\n" + "=" * 65)
        print(" [COMPLETED] ONE-TIME LOGIN SUCCESSFUL!")
        print(" Background Headless Uploader is now permanently authenticated.")
        print(" You can close anything and use your Mac freely.")
        print("=" * 65)
    else:
        print("\n[NOTE] Setup finished. Checking authentication status...")
        await check_status()

async def check_status():
    print("Checking background headless authentication status...")
    uploader = HeadlessYouTubeUploader(headless=True)
    res = await uploader.check_auth_status()
    if res.get("authenticated"):
        print("[AUTHENTICATED] Headless YouTube Studio is logged in and ready for background uploads!")
        print(f"Channel dashboard: {res.get('title')}")
    else:
        print("[NOT AUTHENTICATED] Studio redirected to login or cookies missing.")
        print(f"URL reached: {res.get('url')}")
        print("\nTo authenticate, run either:")
        print("  python scripts/setup_youtube_auth.py --login")
        print("  OR export cookies from Chrome extension into backend/browser_data/youtube_cookies.json")

def import_cookies(source_path: str):
    src = Path(source_path)
    if not src.exists():
        print(f"[ERROR] Source file not found: {src}")
        return
    with open(src, "r") as f:
        data = json.load(f)
    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIES_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[SUCCESS] Imported {len(data)} cookies to {COOKIES_FILE}")
    print("Now run: python scripts/setup_youtube_auth.py --check to verify.")

def main():
    parser = argparse.ArgumentParser(description="SupoClip YouTube Authentication Setup")
    parser.add_argument("--login", action="store_true", help="Launch one-time interactive login window")
    parser.add_argument("--check", action="store_true", help="Check headless background login status")
    parser.add_argument("--import-cookies", type=str, help="Path to exported JSON cookies file")
    
    args = parser.parse_args()
    if args.login:
        asyncio.run(interactive_login())
    elif args.import_cookies:
        import_cookies(args.import_cookies)
    else:
        asyncio.run(check_status())

if __name__ == "__main__":
    main()
