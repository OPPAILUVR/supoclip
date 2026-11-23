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
        
        # Click the ytcp-checkbox-lit element on row 2
        cb = page.locator("ytcp-video-row").nth(1).locator("ytcp-checkbox-lit").first
        await cb.click(force=True)
        await asyncio.sleep(2)
        
        header_text = await page.evaluate("() => document.querySelector('ytcp-table-header')?.innerText || ''")
        print("Header text after click:", header_text.replace('\n', ' | '))
        
        more_btn = page.locator("button:has-text('More actions'), ytcp-button:has-text('More actions')").first
        print("More btn visible:", await more_btn.is_visible())
        if await more_btn.is_visible():
            await more_btn.click(force=True)
            await asyncio.sleep(1.5)
            
            del_item = page.locator("tp-yt-paper-item:has-text('Delete forever'), ytcp-menu-service-item:has-text('Delete forever')").first
            if await del_item.is_visible():
                await del_item.click(force=True)
                await asyncio.sleep(2)
                
                confirm_cb = page.locator("ytcp-dialog ytcp-checkbox-lit, ytcp-dialog paper-checkbox, #confirm-checkbox").first
                if await confirm_cb.count() > 0:
                    await confirm_cb.click(force=True)
                    print("Checked confirmation checkbox in dialog")
                    await asyncio.sleep(1)
                    
                del_btn = page.locator("ytcp-dialog button:has-text('Delete forever'), ytcp-dialog ytcp-button#confirm-button").first
                if await del_btn.count() > 0:
                    await del_btn.click(force=True)
                    print("CONFIRMED DELETE FOREVER!")
                    await asyncio.sleep(6)

        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('ytcp-video-row')).slice(0, 4).map(r => r.querySelector('#video-title')?.innerText.trim() || '');
        }""")
        print("Final Studio rows:", rows)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
