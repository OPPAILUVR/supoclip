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
            
        await asyncio.sleep(3)
        
        # Step through with next button
        next_btn = page.locator("#next-button")
        for step in range(1, 5):
            if await next_btn.is_visible() and await next_btn.is_enabled():
                print(f"Step {step}: Clicking Next...")
                await next_btn.click(force=True)
                await asyncio.sleep(2)
            else:
                print(f"Step {step}: Next button not visible or not enabled!")
                break
                
        # Now check if we are on Visibility
        print("Checking Visibility page elements...")
        badges = page.locator("[id*='step-badge']")
        b_count = await badges.count()
        for i in range(b_count):
            b = badges.nth(i)
            print(f"  Badge {i}: {await b.inner_text()} (state: {await b.get_attribute('state')})")
            
        # Check Public radio button
        public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
        print("Public radio count:", await public_radio.count(), "visible:", await public_radio.is_visible())
        
        # Check Done / Publish button
        done_btn = page.locator("#done-button, #publish-button, button:has-text('Publish'), button:has-text('Save')").first
        print("Done/Publish button count:", await done_btn.count(), "visible:", await done_btn.is_visible(), "disabled:", await done_btn.get_attribute("aria-disabled"))
        
        # Take screenshot of Visibility tab
        vis_shot = "/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/visibility_step_real.png"
        await page.screenshot(path=vis_shot)
        print(f"Saved visibility screenshot to {vis_shot}")
        
        # What if we select Public and click Done?
        if await public_radio.count() > 0 and await public_radio.is_visible():
            await public_radio.click(force=True)
            print("Selected Public radio button!")
            await asyncio.sleep(1)
            
            print("Done button disabled after selecting public?:", await done_btn.get_attribute("aria-disabled"))
            if await done_btn.is_visible() and await done_btn.get_attribute("aria-disabled") != "true":
                print("CLICKING PUBLISH BUTTON NOW!")
                await done_btn.click(force=True)
                await asyncio.sleep(5)
                
                # Check for post publish dialog
                post_shot = "/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/after_publish_click.png"
                await page.screenshot(path=post_shot)
                print(f"Saved post publish screenshot to {post_shot}")

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
