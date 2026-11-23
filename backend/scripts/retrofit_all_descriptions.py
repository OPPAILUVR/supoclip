import asyncio
import json
import logging
import re
from pathlib import Path
from playwright.async_api import async_playwright
from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.utils.video_metadata import build_viral_youtube_description

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [RetrofitDescriptions]: %(message)s"
)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
COOKIES_FILE = BACKEND_DIR / "browser_data" / "youtube_cookies.json"

async def retrofit_all():
    if not COOKIES_FILE.exists():
        logger.error("Cookies file does not exist: %s", COOKIES_FILE)
        return

    with open(COOKIES_FILE, "r") as f:
        cookies = json.load(f)

    # 1. Fetch all clips with youtube_url
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("""
            SELECT id, hook_title, text, reasoning, workflow_meta
            FROM generated_clips
            WHERE workflow_meta->>'youtube_url' IS NOT NULL
            ORDER BY created_at DESC
        """))
        rows = res.fetchall()

    clips = []
    for r in rows:
        meta = dict(r.workflow_meta) if r.workflow_meta else {}
        yt_url = meta.get("youtube_url", "")
        m = re.search(r"/(?:shorts|video)/([a-zA-Z0-9_-]+)", yt_url)
        video_id = m.group(1) if m else None
        if video_id:
            clips.append({
                "id": r.id,
                "video_id": video_id,
                "yt_url": yt_url,
                "title": r.hook_title or meta.get("youtube_title") or "Viral Moment",
                "text": r.text or "",
                "reasoning": r.reasoning or "",
                "streamer": meta.get("streamer") or "Streamer",
                "meta": meta
            })

    logger.info("Found %d clips with YouTube URLs to inspect.", len(clips))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        for idx, clip in enumerate(clips, 1):
            vid = clip["video_id"]
            title = clip["title"]
            streamer = clip["streamer"]
            meta = clip["meta"]

            if meta.get("description_retrofitted"):
                logger.info("[%d/%d] Already marked retrofitted: %s (%s)", idx, len(clips), vid, title[:30])
                continue

            edit_url = f"https://studio.youtube.com/video/{vid}/edit"
            logger.info("[%d/%d] Checking %s (%s)...", idx, len(clips), vid, title[:30])

            try:
                await page.goto(edit_url, timeout=45000, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                desc_box = page.locator("#description-textarea #textbox, [aria-label*='Tell viewers' i]").first
                if await desc_box.count() == 0:
                    logger.warning("Could not find description box for %s, skipping.", vid)
                    continue

                curr_text = (await desc_box.inner_text()).strip()
                if "Featured Streamer" in curr_text and len(curr_text) > 80:
                    logger.info("Description already present on YouTube for %s.", vid)
                    # Mark in DB
                    meta["description_retrofitted"] = True
                    async with AsyncSessionLocal() as session:
                        await session.execute(
                            text("UPDATE generated_clips SET workflow_meta = :meta WHERE id = :id"),
                            {"meta": json.dumps(meta), "id": clip["id"]}
                        )
                        await session.commit()
                    continue

                full_title = title if title.endswith("#shorts") else f"{title} #shorts"
                rich_desc = build_viral_youtube_description(
                    title=full_title,
                    streamer_name=streamer,
                    hook_text=clip["text"],
                    reasoning=clip["reasoning"]
                )

                await desc_box.click(force=True)
                await desc_box.fill(rich_desc)
                await page.wait_for_timeout(1000)

                save_btn = page.locator("#save, #save-button, button:has-text('Save')").first
                if await save_btn.count() > 0 and await save_btn.is_visible():
                    is_disabled = (await save_btn.get_attribute("aria-disabled") == "true") or (await save_btn.get_attribute("disabled") is not None)
                    if not is_disabled:
                        await save_btn.click(force=True)
                        logger.info("Saved description for %s (%s)!", vid, title[:30])
                        await page.wait_for_timeout(2500)
                    else:
                        logger.info("Save button disabled (no changes needed) for %s.", vid)
                else:
                    logger.warning("Save button not found or not visible for %s.", vid)

                # Update DB
                meta["description_retrofitted"] = True
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text("UPDATE generated_clips SET workflow_meta = :meta WHERE id = :id"),
                        {"meta": json.dumps(meta), "id": clip["id"]}
                    )
                    await session.commit()

            except Exception as e:
                logger.error("Error updating %s: %s", vid, e)

            await asyncio.sleep(1.5)

        await browser.close()
        logger.info("Retrofit complete for all videos!")

if __name__ == "__main__":
    asyncio.run(retrofit_all())
