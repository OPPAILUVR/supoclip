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
        
        # Row 2 is "Breaking This Object Instantly Erased xQc #shorts"
        row = page.locator("ytcp-video-row").nth(1)
        title = await row.locator("#video-title").inner_text()
        print(f"Targeting row 2: {title}")
        
        # Click on the Visibility text / dropdown on row 2
        vis_cell = row.locator("[aria-label*='Public' i], [aria-label*='visibility' i], #visibility, ytcp-video-visibility-select").first
        if await vis_cell.count() > 0:
            print("Clicking visibility cell...")
            await vis_cell.click(force=True)
            await asyncio.sleep(2)
            
            # Select Private radio button in the popup
            private_radio = page.locator("tp-yt-paper-radio-button[name='PRIVATE'], tp-yt-paper-radio-button:has-text('Private')").first
            if await private_radio.count() > 0:
                print("Selecting Private radio button...")
                await private_radio.click(force=True)
                await asyncio.sleep(1)
                
                # Click Save
                save_btn = page.locator("button:has-text('Save'), ytcp-button#save-button, [aria-label='Save']").first
                if await save_btn.count() > 0:
                    await save_btn.click(force=True)
                    print("Saved as Private successfully!")
                    await asyncio.sleep(3)

        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        rows = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('ytcp-video-row')).slice(0, 4).map(r => {
                const t = r.querySelector('#video-title')?.innerText.trim() || '';
                return t + ' -> ' + r.innerText.replace(/\\n+/g, ' | ').substring(0, 80);
            });
        }""")
        for r in rows:
            print(r)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
