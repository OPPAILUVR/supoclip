import asyncio
import logging
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DraftCleaner")

async def clean_all_drafts(max_batches: int = 5):
    uploader = HeadlessYouTubeUploader(headless=True)
    async with async_playwright() as p:
        ctx = await uploader.get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        logger.info("Starting YouTube Studio Draft Purge...")
        
        for batch in range(1, max_batches + 1):
            logger.info(f"\n==========================================")
            logger.info(f"--- BATCH {batch}/{max_batches} ---")
            await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            # 1. Apply Visibility: Draft filter
            logger.info("Applying Visibility: Draft filter...")
            filter_bar = page.locator("ytcp-filter-bar, #filter-icon, input[placeholder*='Filter']").first
            await filter_bar.click()
            await asyncio.sleep(1)
            
            vis_option = page.locator("tp-yt-paper-item:has-text('Visibility')").first
            if await vis_option.count() == 0 or not await vis_option.is_visible():
                await filter_bar.click()
                await asyncio.sleep(1)
            
            await vis_option.click()
            await asyncio.sleep(1)
            
            cb4 = page.locator("#checkbox-4").first
            await cb4.click()
            await asyncio.sleep(0.5)
            
            apply_btn = page.locator("ytcp-button#apply-button, button:has-text('Apply'), ytcp-button:has-text('Apply')").first
            await apply_btn.click()
            await asyncio.sleep(4)
            
            # Wait for table rows to be rendered
            try:
                await page.wait_for_selector("ytcp-video-row", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(2)
            
            footer_text = await page.evaluate("() => document.querySelector('ytcp-table-footer')?.innerText.replace(/\\n+/g, ' | ') || 'no footer'")
            logger.info(f"Current Drafts footer: {footer_text}")
            
            # Count rows
            rows = await page.locator("ytcp-video-row").count()
            logger.info(f"Draft rows visible on this page: {rows}")
            if rows == 0:
                logger.info("🎉 SUCCESS: No more drafts found! YouTube Studio Shorts tab is completely clean of drafts.")
                break
                
            # Select all on page using JS click
            logger.info("Selecting all drafts on page via JS click...")
            toolbar = page.locator("ytcp-select#additional-action-options #trigger, ytcp-select#additional-action-options").first
            
            for try_idx in range(4):
                await page.evaluate("""() => {
                    const cb = document.querySelector('#selection-checkbox') || document.querySelector('ytcp-checkbox-lit#selection-checkbox');
                    if (cb) cb.click();
                }""")
                await asyncio.sleep(2.5)
                if await toolbar.is_visible():
                    logger.info("Bulk actions toolbar is visible!")
                    break
                logger.warning(f"Toolbar not visible on attempt {try_idx+1}, retrying...")
                await asyncio.sleep(1)
            
            if not await toolbar.is_visible():
                logger.error("Could not activate bulk actions toolbar.")
                break
                
            # Open More actions dropdown
            logger.info("Opening More actions dropdown...")
            await toolbar.click(force=True)
            await asyncio.sleep(1.5)
            
            del_item = page.locator("tp-yt-paper-item:has-text('Delete forever')").first
            if await del_item.count() == 0:
                logger.error("Could not find 'Delete forever' menu option.")
                break
                
            await del_item.click(force=True)
            await asyncio.sleep(2)
            
            # Confirmation dialog
            dialog = page.locator("ytcp-confirmation-dialog, ytcp-dialog").filter(has_text="Delete forever").first
            if await dialog.count() == 0:
                logger.error("Confirmation dialog did not appear.")
                break
                
            logger.info("Checking 'I understand that deleting is permanent'...")
            cb = dialog.locator("ytcp-checkbox-lit, tp-yt-paper-checkbox, #confirm-checkbox, input[type=checkbox]").first
            await cb.click(force=True)
            await asyncio.sleep(1)
            
            confirm_btn = dialog.locator("ytcp-button#confirm-button, button:has-text('Delete forever')").first
            if not await confirm_btn.is_enabled():
                logger.warning("Confirm button not enabled yet, waiting 1s...")
                await asyncio.sleep(1)
                
            logger.info(f"Clicking final 'Delete forever' button for batch {batch}...")
            await confirm_btn.click(force=True)
            
            logger.info("Waiting 15 seconds for YouTube backend to execute bulk deletion...")
            await asyncio.sleep(15)
            
            shot_path = f"/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/draft_cleanup_batch_{batch}.png"
            await page.screenshot(path=shot_path)
            logger.info(f"Batch {batch} complete. Screenshot saved to {shot_path}")

        logger.info("\nFinal check: Checking Shorts tab without filters...")
        await page.goto("https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short", timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        final_footer = await page.evaluate("() => document.querySelector('ytcp-table-footer')?.innerText.replace(/\\n+/g, ' | ') || 'no footer'")
        logger.info(f"Final Shorts table footer: {final_footer}")
        await page.screenshot(path="/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/studio_shorts_after_purge.png")
        
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(clean_all_drafts(max_batches=5))
