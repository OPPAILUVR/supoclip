#!/usr/bin/env python3
"""
Retroactively generate and attach high-CTR viral thumbnails to YouTube Shorts uploaded today,
and purge any leftover drafts to enforce the Zero Drafts Policy.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader
from src.services.thumbnail_generator import generate_viral_thumbnail

TODAY_VIDEOS = [
    {
        "id": "8D6o_uz8AXc",
        "title": "asmong Demolished Ridiculous GTA Girlfriend Simulator",
        "streamer": "asmongold"
    },
    {
        "id": "cAcU2Wvyjr8",
        "title": "When Montys Spiked Drink Shocked xqc",
        "streamer": "xqc"
    },
    {
        "id": "8gUAQYUCwwA",
        "title": "xqc Snapped When Sudden Ambush Hit",
        "streamer": "xqc"
    },
    {
        "id": "TQKO2E9g0Bo",
        "title": "asmong Exposes Shady Early Review Incentives",
        "streamer": "asmongold"
    }
]

TEMP_DIR = Path("/tmp/supoclip_thumbs")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

def download_short(video_id: str) -> Path:
    out_file = TEMP_DIR / f"{video_id}.mp4"
    if out_file.exists():
        return out_file
    
    url = f"https://www.youtube.com/shorts/{video_id}"
    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=android",
        "-f", "best[ext=mp4]/best",
        "-o", str(out_file),
        url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback to direct youtube URL
        cmd2 = ["yt-dlp", "-f", "18/best", "-o", str(out_file), f"https://www.youtube.com/watch?v={video_id}"]
        subprocess.run(cmd2, capture_output=True, text=True)
    return out_file

async def main():
    uploader = HeadlessYouTubeUploader(headless=True)
    
    # 1. First generate all thumbnails
    thumbs = {}
    for item in TODAY_VIDEOS:
        vid = item["id"]
        title = item["title"]
        streamer = item["streamer"]
        print(f"Downloading short {vid}...")
        mp4_path = download_short(vid)
        if not mp4_path.exists() or mp4_path.stat().st_size == 0:
            print(f"Failed to download {vid}")
            continue
        
        print(f"Generating viral thumbnail for {title}...")
        thumb_path = generate_viral_thumbnail(
            video_path=mp4_path,
            hook_title=title,
            streamer_name=streamer,
            output_path=TEMP_DIR / f"{vid}_thumb.jpg"
        )
        print(f"Generated: {thumb_path}")
        thumbs[vid] = thumb_path

    # 2. Open YouTube Studio and upload thumbnails to each video
    async with async_playwright() as p:
        context = await uploader.get_context(p)
        page = context.pages[0] if context.pages else await context.new_page()
        
        for vid, t_path in thumbs.items():
            edit_url = f"https://studio.youtube.com/video/{vid}/edit"
            print(f"\nNavigating to {edit_url}...")
            await page.goto(edit_url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)
            
            thumb_input = page.locator('ytcp-thumbnail-uploader input[type="file"], input#file-loader[accept*="image"]').first
            if await thumb_input.count() > 0:
                print(f"Attaching thumbnail {t_path.name} to video {vid}...")
                await thumb_input.set_input_files(str(t_path))
                await page.wait_for_timeout(4000)
                
                save_btn = page.locator('#save, button:has-text("Save")').first
                if await save_btn.is_enabled():
                    await save_btn.click()
                    print(f"Successfully saved thumbnail for {vid}!")
                    await page.wait_for_timeout(4000)
                else:
                    print(f"Save button not enabled for {vid}")
            else:
                print(f"Could not locate thumbnail input for {vid}")
                
        # 3. Clean up leftover drafts (Zero Drafts Policy)
        print("\nChecking for and purging leftover drafts...")
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=45000, wait_until="networkidle")
        await page.wait_for_timeout(3000)
        
        rows = await page.locator("ytcp-video-row").all()
        for r in rows:
            txt = await r.inner_text()
            if "Draft" in txt:
                title_el = r.locator("a#video-title, #video-title")
                d_title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else "Draft"
                print(f"Deleting leftover draft: '{d_title}'...")
                await r.hover()
                await page.wait_for_timeout(800)
                opt_b = r.locator("#options-button, button[aria-label*='Options' i]").first
                if await opt_b.count() > 0:
                    await opt_b.click(force=True)
                    await page.wait_for_timeout(800)
                    del_m = page.locator("tp-yt-paper-item:has-text('Delete forever')").first
                    if await del_m.count() > 0:
                        await del_m.click(force=True)
                        await page.wait_for_timeout(800)
                        c_dialog = page.locator("ytcp-confirmation-dialog").filter(has_text="Delete").first
                        c_cb = c_dialog.locator("ytcp-checkbox-lit, #confirm-checkbox").first
                        if await c_cb.count() > 0:
                            await c_cb.click(force=True)
                        c_b = c_dialog.locator("ytcp-button#confirm-button, button:has-text('Delete forever')").first
                        if await c_b.count() > 0:
                            await c_b.click(force=True)
                            print(f"Deleted draft: '{d_title}'!")
                            await page.wait_for_timeout(3000)

        # 4. Final verification screenshot
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=45000, wait_until="networkidle")
        await page.wait_for_timeout(3000)
        await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/studio_shorts_final_all_thumbnails.png")
        print("\nFinal verification screenshot saved!")

if __name__ == "__main__":
    asyncio.run(main())
