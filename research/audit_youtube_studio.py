#!/usr/bin/env python3
"""
Deep YouTube Studio Content & Analytics Auditor (Robust JS Evaluation).
"""

import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StudioAuditor")

BACKEND_DIR = Path("/Users/luv/.gemini/antigravity/scratch/supoclip/backend")
PROFILE_DIR = BACKEND_DIR / "browser_data" / "youtube_profile"
COOKIES_FILE = BACKEND_DIR / "browser_data" / "youtube_cookies.json"
OUTPUT_JSON = BACKEND_DIR / "browser_data" / "youtube_studio_audit.json"
SCREENSHOT_DIR = BACKEND_DIR / "browser_data" / "audit_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

async def audit():
    async with async_playwright() as p:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
        ]
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1400, "height": 1000},
            args=args,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        if COOKIES_FILE.exists():
            try:
                with open(COOKIES_FILE, "r") as f:
                    cookies = json.load(f)
                formatted = []
                for c in cookies:
                    cd = {
                        "name": c.get("name"),
                        "value": c.get("value"),
                        "domain": c.get("domain"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", False),
                        "httpOnly": c.get("httpOnly", False),
                    }
                    if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
                        cd["sameSite"] = c["sameSite"]
                    formatted.append(cd)
                await context.add_cookies(formatted)
                logger.info("Loaded %d cookies into context", len(formatted))
            except Exception as e:
                logger.warning("Cookie load error: %s", e)

        page = context.pages[0] if context.pages else await context.new_page()

        try:
            logger.info("Navigating to YouTube Studio...")
            await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", wait_until="domcontentloaded")
            await asyncio.sleep(6)

            # Take screenshot of the top of the table
            top_shot = SCREENSHOT_DIR / "shorts_top.png"
            await page.screenshot(path=str(top_shot))

            # Scroll down to reveal all rows
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(2)
            bottom_shot = SCREENSHOT_DIR / "shorts_bottom.png"
            await page.screenshot(path=str(bottom_shot))

            # Extract row data directly via JavaScript in the DOM
            rows_data = await page.evaluate("""() => {
                const rows = Array.from(document.querySelectorAll('ytcp-video-row'));
                return rows.map((r, i) => {
                    const titleElem = r.querySelector('#video-title, a#video-title');
                    const link = titleElem ? titleElem.getAttribute('href') : '';
                    let vidId = '';
                    if (link && link.includes('/video/')) {
                        vidId = link.split('/video/')[1].split('/')[0];
                    }
                    return {
                        index: i,
                        title: titleElem ? titleElem.innerText.trim() : '',
                        video_id: vidId,
                        link: link,
                        all_text: r.innerText.trim().split('\\n').map(s => s.trim()).filter(Boolean)
                    };
                });
            }""")

            logger.info("Extracted %d video rows from table DOM:", len(rows_data))
            for r in rows_data:
                logger.info("Row %d: [%s] %s | %s", r["index"], r["video_id"], r["title"], " | ".join(r["all_text"][:8]))

            detailed_videos = []
            for item in rows_data:
                vid_id = item.get("video_id")
                if not vid_id:
                    continue

                logger.info("\n>>> Inspecting [%s] %s <<<", vid_id, item["title"])

                # 1. Edit page
                edit_url = f"https://studio.youtube.com/video/{vid_id}/edit"
                await page.goto(edit_url, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                edit_data = await page.evaluate("""() => {
                    const titleBox = document.querySelector('#textbox[aria-label*=\"title\"], ytcp-mention-textbox[label*=\"Title\"] #textbox');
                    const descBox = document.querySelector('#description-textarea #textbox, #textbox[aria-label*=\"description\"]');
                    const tagChips = Array.from(document.querySelectorAll('ytcp-chip span.chip-text')).map(c => c.innerText.trim());
                    return {
                        title: titleBox ? titleBox.innerText.trim() : '',
                        description: descBox ? descBox.innerText.trim() : '',
                        tags: tagChips
                    };
                }""")

                # 2. Analytics page
                analytics_url = f"https://studio.youtube.com/video/{vid_id}/analytics/tab-overview"
                await page.goto(analytics_url, wait_until="domcontentloaded")
                await asyncio.sleep(4)

                analytics_shot = SCREENSHOT_DIR / f"analytics_{vid_id}.png"
                await page.screenshot(path=str(analytics_shot))

                analytics_text = await page.evaluate("() => document.body.innerText")
                # Parse lines from analytics
                lines = [l.strip() for l in analytics_text.split("\n") if l.strip()]

                detailed_videos.append({
                    "video_id": vid_id,
                    "table_info": item,
                    "edit_details": edit_data,
                    "analytics_summary": lines[:60],
                    "analytics_screenshot": str(analytics_shot)
                })

            final_report = {
                "channel_id": "UCfSSIQbWKw7Pl6jCdHD_rxg",
                "audited_at": asyncio.get_event_loop().time(),
                "total_rows_found": len(rows_data),
                "videos": detailed_videos
            }

            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(final_report, f, indent=2)

            logger.info("AUDIT COMPLETE! Saved report to %s", OUTPUT_JSON)

        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(audit())
