import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

async def delete_all_drafts():
    uploader = HeadlessYouTubeUploader(headless=True)
    async with async_playwright() as p:
        ctx = await uploader.get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        print("Navigating to Shorts content page...")
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        
        # Check rows
        rows = await page.locator("ytcp-video-row").count()
        print(f"Total rows found: {rows}")
        
        # Look for draft filter or select all
        # Let us see what drafts exist
        draft_rows = []
        for i in range(rows):
            row = page.locator("ytcp-video-row").nth(i)
            text = await row.inner_text()
            if "Draft" in text:
                draft_rows.append(i)
                
        print(f"Found {len(draft_rows)} drafts on page 1.")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(delete_all_drafts())
