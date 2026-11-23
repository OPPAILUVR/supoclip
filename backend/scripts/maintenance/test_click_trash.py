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
        
        row = page.locator("ytcp-video-row").nth(1)
        text = await row.inner_text()
        print(f"Row 2 text snippet: {text[:60]}")
        
        if "Draft" in text:
            await row.hover()
            await asyncio.sleep(1)
            trash_btn = row.locator("button[aria-label*='Delete' i], [aria-label*='Discard draft' i], #delete-button").first
            await trash_btn.click(force=True)
            await asyncio.sleep(2)
            
            # Screenshot confirmation dialog
            await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/draft_delete_dialog.png")
            print("Saved delete dialog screenshot.")
            
            # Find confirmation button
            confirm_btn = page.locator("ytcp-button#confirm-button, button:has-text('Delete draft'), button:has-text('Delete forever'), #delete-button").last
            print("Confirm button count:", await confirm_btn.count(), "visible:", await confirm_btn.is_visible())
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
