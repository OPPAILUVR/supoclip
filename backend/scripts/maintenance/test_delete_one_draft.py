import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

async def main():
    uploader = HeadlessYouTubeUploader(headless=True)
    async with async_playwright() as p:
        ctx = await uploader.get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        
        # Hover over the 2nd row (which is definitely a draft) to see options
        row = page.locator("ytcp-video-row").nth(1)
        title = await row.locator("#video-title").inner_text()
        text = await row.inner_text()
        print(f"Row 2 title: {title}, text: {text[:60]}")
        
        if "Draft" in text:
            # Hover over row to reveal action buttons
            await row.hover()
            await asyncio.sleep(1)
            
            # Check options button (three dots or trash button)
            trash_btn = row.locator("button[aria-label*='Delete' i], [aria-label*='Discard draft' i], #delete-button").first
            options_btn = row.locator("#options-button, button[aria-label*='Options' i], [aria-label*='Action menu' i]").first
            
            print(f"Trash btn count: {await trash_btn.count()}, Options btn count: {await options_btn.count()}")
            
            # Let's take a screenshot of hovered row
            await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/draft_hover_test.png")
            print("Saved hover screenshot.")
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
