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
        
        row = page.locator("ytcp-video-row").first
        edit_draft_btn = row.locator("button:has-text('Edit draft'), a:has-text('Edit draft')").first
        if await edit_draft_btn.count() > 0:
            await edit_draft_btn.click(force=True)
        else:
            await row.locator("#video-title").click(force=True)
            
        await asyncio.sleep(4)
        
        # Grab text of dialog
        dialog = page.locator("ytcp-uploads-dialog, ytcp-video-metadata-editor-dialog, ytcp-dialog").first
        dialog_text = await dialog.inner_text() if await dialog.count() > 0 else await page.locator("body").inner_text()
        print("=== DIALOG TEXT SNIPPET ===")
        print(dialog_text[:1200])
        
        # Check step badges
        badges = page.locator("[id*='step-badge']")
        b_count = await badges.count()
        print(f"\nStep badges count: {b_count}")
        for i in range(b_count):
            b = badges.nth(i)
            print(f"  Badge {i}: {await b.inner_text()} (state: {await b.get_attribute('state')})")
            
        # Check if Next button is enabled
        next_btn = page.locator("#next-button")
        print(f"Next button visible: {await next_btn.is_visible()}, enabled: {await next_btn.is_enabled()}")
        
        # Check if Done/Save/Publish button is visible
        done_btn = page.locator("#done-button")
        print(f"Done button visible: {await done_btn.is_visible()}, enabled: {await done_btn.is_enabled()}")

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
