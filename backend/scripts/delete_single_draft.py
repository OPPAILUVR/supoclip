import asyncio
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

async def check():
    uploader = HeadlessYouTubeUploader(headless=True)
    async with async_playwright() as p:
        ctx = await uploader.get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        
        # Apply Draft filter
        filter_bar = page.locator("ytcp-filter-bar, #filter-icon, input[placeholder*='Filter']").first
        await filter_bar.click()
        await asyncio.sleep(1)
        vis_option = page.locator("tp-yt-paper-item:has-text('Visibility')").first
        await vis_option.click()
        await asyncio.sleep(1)
        cb4 = page.locator("#checkbox-4").first
        await cb4.click()
        await asyncio.sleep(0.5)
        apply_btn = page.locator("ytcp-button#apply-button, button:has-text('Apply'), ytcp-button:has-text('Apply')").first
        await apply_btn.click()
        await asyncio.sleep(3)
        
        # Click the delete-draft-button via JS
        clicked = await page.evaluate("""() => {
            const btn = document.querySelector('.delete-draft-button button, .delete-draft-button, [aria-label=\"Delete video\"]');
            if (!btn) return 'not-found';
            btn.click();
            return 'clicked: ' + btn.tagName + '.' + btn.className;
        }""")
        print("JS click on delete-draft-button:", clicked)
        await asyncio.sleep(2)
        
        dialog = page.locator("ytcp-confirmation-dialog, ytcp-dialog").filter(has_text="Delete").first
        print("Dialog visible?", await dialog.is_visible())
        if await dialog.is_visible():
            print("Dialog text:\n", await dialog.inner_text())
            cb = dialog.locator("ytcp-checkbox-lit, tp-yt-paper-checkbox, #confirm-checkbox, input[type=checkbox]").first
            if await cb.count() > 0:
                await cb.click(force=True)
                await asyncio.sleep(0.5)
            confirm = dialog.locator("ytcp-button#confirm-button, button:has-text('Delete forever'), button:has-text('Delete video'), button:has-text('Delete')").first
            await confirm.click(force=True)
            print("Successfully confirmed delete!")
            await asyncio.sleep(4)
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(check())
