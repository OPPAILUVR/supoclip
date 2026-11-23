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
        
        # Check header checkbox
        select_all = page.locator("ytcp-checkbox-lit#select-all-checkbox, #select-all-checkbox, th ytcp-checkbox-lit, ytcp-table-header ytcp-checkbox-lit").first
        print("Select all checkbox count:", await select_all.count())
        
        if await select_all.count() > 0:
            await select_all.click(force=True)
            await asyncio.sleep(2)
            
            # Screenshot after select all
            await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/studio_bulk_selected.png")
            print("Saved bulk selected screenshot.")
            
            # Check what action buttons appeared
            actions = await page.evaluate("""() => {
                const bar = document.querySelector("ytcp-bulk-actions, #actions-bar, ytcp-table-header");
                return bar ? bar.innerText.replace(/\\n+/g, " | ") : "no-bar";
            }""")
            print("Action bar text:", actions)
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
