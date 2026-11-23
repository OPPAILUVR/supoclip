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
        
        select_all = page.locator("ytcp-checkbox-lit#select-all-checkbox, #select-all-checkbox").first
        await select_all.click(force=True)
        await asyncio.sleep(1)
        
        more_actions = page.locator("button:has-text('More actions'), ytcp-button:has-text('More actions'), #actions-menu-button").first
        if await more_actions.count() > 0:
            await more_actions.click(force=True)
            await asyncio.sleep(1)
            menu_items = await page.evaluate("""() => {
                const items = document.querySelectorAll("tp-yt-paper-item, ytcp-menu-service-item, paper-item");
                return Array.from(items).map(i => i.innerText.trim());
            }""")
            print("More actions menu items:", menu_items)
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
