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
        
        # Check rows for Drafts
        for attempt in range(5):
            rows = page.locator("ytcp-video-row")
            count = await rows.count()
            found_draft = False
            for i in range(count):
                row = rows.nth(i)
                text = await row.inner_text()
                if "Draft" in text or "Cancel upload" in text:
                    found_draft = True
                    print(f"Deleting draft at row {i+1}...")
                    await row.hover()
                    await asyncio.sleep(1)
                    
                    # Look for options menu or delete button on this row
                    opt_btn = row.locator("#options-button, button[aria-label*='Options' i], [aria-label*='Action menu' i], button[aria-label*='Delete' i]").first
                    if await opt_btn.count() > 0:
                        await opt_btn.click(force=True)
                        await asyncio.sleep(1)
                        
                        # In the menu that opened
                        del_item = page.locator("tp-yt-paper-item:has-text('Delete forever'), ytcp-menu-service-item:has-text('Delete forever'), tp-yt-paper-item:has-text('Discard draft')").first
                        if await del_item.count() > 0 and await del_item.is_visible():
                            await del_item.click(force=True)
                            await asyncio.sleep(1)
                            
                            # Confirm dialog
                            confirm_cb = page.locator("ytcp-dialog ytcp-checkbox-lit, ytcp-dialog paper-checkbox, #confirm-checkbox").first
                            if await confirm_cb.count() > 0:
                                await confirm_cb.click(force=True)
                                await asyncio.sleep(0.5)
                            
                            del_btn = page.locator("ytcp-dialog button:has-text('Delete forever'), ytcp-dialog ytcp-button#confirm-button, ytcp-dialog button:has-text('Delete')").first
                            if await del_btn.count() > 0 and await del_btn.is_enabled():
                                await del_btn.click(force=True)
                                print("Successfully deleted draft!")
                                await asyncio.sleep(3)
                                break
                    elif "Cancel upload" in text:
                        cancel_btn = row.locator("button:has-text('Cancel upload'), [aria-label*='Cancel upload']").first
                        if await cancel_btn.count() > 0:
                            await cancel_btn.click(force=True)
                            print("Cancelled pending upload!")
                            await asyncio.sleep(2)
                            break
            if not found_draft:
                print("No more drafts found!")
                break
                
        await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/studio_final_clean.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
