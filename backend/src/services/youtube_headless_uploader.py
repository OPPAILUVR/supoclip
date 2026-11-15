#!/usr/bin/env python3
"""
Headless YouTube Uploader for SupoClip / Antigravity.
Runs 100% in the background via Playwright with NO GUI, NO window stealing,
and NO file-dialog popups, allowing the user to use their Mac completely freely.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright, BrowserContext, Page

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = BACKEND_DIR / "browser_data" / "youtube_profile"
COOKIES_FILE = BACKEND_DIR / "browser_data" / "youtube_cookies.json"

logger = logging.getLogger("HeadlessYouTubeUploader")

class HeadlessYouTubeUploader:
    def __init__(self, headless: bool = True, profile_dir: Path = PROFILE_DIR, cookies_file: Path = COOKIES_FILE):
        self.headless = headless
        self.profile_dir = profile_dir
        self.cookies_file = cookies_file
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def get_context(self, p) -> BrowserContext:
        """Launches an isolated persistent browser context in the background."""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--window-size=1280,800",
        ]

        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 800},
            args=args,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        # If user exported cookies from Chrome, import them
        if self.cookies_file.exists():
            try:
                with open(self.cookies_file, "r") as f:
                    raw_cookies = json.load(f)
                
                # Format cookies for playwright
                formatted_cookies = []
                for c in raw_cookies:
                    cookie_dict = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".youtube.com"),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        cookie_dict["secure"] = c["secure"]
                    if "httpOnly" in c:
                        cookie_dict["httpOnly"] = c["httpOnly"]
                    if "sameSite" in c:
                        s_val = c["sameSite"]
                        if s_val in ["Strict", "Lax", "None"]:
                            cookie_dict["sameSite"] = s_val
                    formatted_cookies.append(cookie_dict)
                
                await context.add_cookies(formatted_cookies)
                logger.info("Loaded %d cookies from %s", len(formatted_cookies), self.cookies_file)
            except Exception as e:
                logger.warning("Could not load cookies from %s: %s", self.cookies_file, e)

        return context

    async def check_auth_status(self) -> Dict[str, Any]:
        """Checks if the background browser has an active logged-in YouTube session."""
        async with async_playwright() as p:
            context = await self.get_context(p)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                logger.info("Navigating to YouTube Studio in background to check login status...")
                await page.goto("https://studio.youtube.com", timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                current_url = page.url
                
                if "accounts.google.com" in current_url:
                    logger.warning("Studio redirected to Google Sign-in. Account is not logged in.")
                    return {"authenticated": False, "url": current_url}
                elif "studio.youtube.com" in current_url:
                    logger.info("Studio successfully authenticated!")
                    # Check channel name or avatar if available
                    title = await page.title()
                    return {"authenticated": True, "title": title, "url": current_url}
                else:
                    return {"authenticated": False, "url": current_url}
            finally:
                await context.close()

    async def check_and_handle_reauth(self, page: Page, context: BrowserContext, timeout_seconds: int = 600) -> bool:
        """
        Detects if YouTube Studio presents Google's 'Verify it's you' security modal.
        If detected, triggers the reauth challenge, extracts the 2-digit verification code
        and mobile instructions, writes them to browser_data/reauth_prompt.json, and waits
        for the user to confirm the prompt on their iPhone/device.
        Upon approval, saves updated session state so subsequent uploads are seamless.
        """
        confirm_btn = page.locator("#confirm-button, ytcp-auth-confirmation-dialog #confirm-button").first
        has_verify = await page.locator("text='Verify it'").count() > 0 or await page.locator("ytcp-auth-confirmation-dialog").count() > 0
        if has_verify and await confirm_btn.count() > 0 and await confirm_btn.is_visible():
            logger.warning("Google 'Verify it\\'s you' security prompt detected on YouTube Studio!")
            popup_future = asyncio.Future()
            page.on("popup", lambda p: popup_future.set_result(p) if not popup_future.done() else None)
            await confirm_btn.click(force=True)
            
            try:
                popup = await asyncio.wait_for(popup_future, timeout=12)
            except asyncio.TimeoutError:
                logger.error("Popup window for Google reauth failed to open.")
                raise PermissionError("Google verification modal appeared but reauth popup failed to open.")
            
            logger.info("Reauth popup opened: %s", popup.url)
            try:
                await popup.wait_for_url(lambda u: "/challenge/" in u, timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(2)
            
            body_text = await popup.inner_text("body")
            code = None
            import re
            code_match = re.search(r'\b(\d{2})\b', body_text)
            if code_match and "tap" in body_text.lower():
                code = code_match.group(1)
            
            prompt_info = {
                "timestamp": asyncio.get_event_loop().time(),
                "code": code,
                "title": await popup.title(),
                "text": body_text[:400],
                "status": "waiting_user_confirmation"
            }
            
            prompt_file = BACKEND_DIR / "browser_data" / "reauth_prompt.json"
            with open(prompt_file, "w") as f:
                json.dump(prompt_info, f, indent=2)
            
            try:
                await popup.screenshot(path=str(BACKEND_DIR / "browser_data" / "current_google_prompt.png"))
            except Exception:
                pass
            
            logger.critical(
                "⚠️  GOOGLE SECURITY VERIFICATION REQUIRED! ⚠️\n"
                "Code to tap on iPhone 16: [%s]\n"
                "Instructions: %s\n"
                "Waiting up to %d seconds for approval on device...",
                code or "CHECK NOTIFICATION", prompt_info["text"].replace("\n", " "), timeout_seconds
            )
            print(f"\n=======================================================\n>>> GOOGLE SECURITY CODE FOR IPHONE: [{code or 'CHECK PHONE'}] <<<\n=======================================================\n", flush=True)

            reauth_confirmed = False
            start_w = asyncio.get_event_loop().time()
            sec_code_file = BACKEND_DIR / "browser_data" / "security_code.txt"
            while asyncio.get_event_loop().time() - start_w < timeout_seconds:
                if popup.is_closed():
                    logger.info("Reauth popup closed! User confirmed verification on device.")
                    reauth_confirmed = True
                    break
                try:
                    if popup.url.startswith("https://studio.youtube.com"):
                        logger.info("Popup redirected to YouTube Studio reauth completion!")
                        reauth_confirmed = True
                        await asyncio.sleep(2)
                        break

                    # Check if user provided a security code via browser_data/security_code.txt
                    if sec_code_file.exists():
                        code_to_enter = sec_code_file.read_text().strip()
                        if code_to_enter:
                            sec_code_file.unlink(missing_ok=True)
                            logger.info("Found user security code: %s. Submitting to Google prompt...", code_to_enter)
                            input_elem = popup.locator("input[type='tel'], input[type='text'], input[id*='Pin'], input[name*='code'], input[aria-label*='code'], input").first
                            if await input_elem.count() > 0 and await input_elem.is_visible():
                                await input_elem.fill(code_to_enter)
                                await asyncio.sleep(0.5)
                                next_btn = popup.locator("button:has-text('Next'), #next, div[role='button']:has-text('Next')").first
                                if await next_btn.count() > 0:
                                    await next_btn.click(force=True)
                                    logger.info("Submitted security code and clicked Next!")
                                    await asyncio.sleep(3)
                except Exception as loop_err:
                    logger.debug("Reauth loop check: %s", loop_err)
                await asyncio.sleep(2)
            
            if not reauth_confirmed:
                prompt_info["status"] = "timed_out"
                with open(prompt_file, "w") as f:
                    json.dump(prompt_info, f, indent=2)
                raise TimeoutError(f"Google device verification timed out after {timeout_seconds} seconds. Please approve prompt on phone to proceed.")

            try:
                state_file = BACKEND_DIR / "browser_data" / "storage_state.json"
                await context.storage_state(path=str(state_file))
                cookies = await context.cookies()
                with open(self.cookies_file, "w") as f:
                    json.dump(cookies, f, indent=2)
                logger.info("Updated storage state and cookies permanently saved after re-auth!")
            except Exception as save_err:
                logger.warning("Could not persist cookies after re-auth: %s", save_err)

            prompt_info["status"] = "confirmed"
            with open(prompt_file, "w") as f:
                json.dump(prompt_info, f, indent=2)
            await asyncio.sleep(3)
            return True
        return False

    async def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list,
        is_short: bool = True
    ) -> Dict[str, Any]:
        """
        Uploads a video completely headlessly with zero desktop interference.
        Attaches video file directly via set_input_files, fills metadata, sets Public, and publishes.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Ensure title fits Shorts requirements
        upload_title = title[:95]
        if is_short and "#shorts" not in upload_title.lower():
            upload_title = f"{upload_title} #shorts"[:100]

        async with async_playwright() as p:
            context = await self.get_context(p)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                logger.info("Opening YouTube Studio in background...")
                await page.goto("https://studio.youtube.com", timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                
                if "accounts.google.com" in page.url:
                    raise PermissionError("YouTube Studio is not authenticated. Please import cookies or perform one-time login.")

                # Click Create button or go to upload URL directly
                logger.info("Initiating upload dialog...")
                create_btn = page.locator("#create-icon, button:has-text('Create'), #upload-button, [aria-label='Upload videos']").first
                if await create_btn.count() > 0:
                    await create_btn.click(force=True)
                    await asyncio.sleep(1)
                    upload_option = page.locator("tp-yt-paper-item:has-text('Upload videos')").first
                    if await upload_option.count() > 0:
                        await upload_option.click(force=True)

                # Wait for file input element
                file_input = page.locator("input[type='file']")
                await file_input.wait_for(state="attached", timeout=15000)
                
                logger.info("Attaching video file: %s (silently in background)", video_path.name)
                await file_input.set_input_files(str(video_path))

                # Wait for upload modal to transition to details view
                logger.info("Waiting for upload details dialog...")
                await page.wait_for_selector("#textbox[aria-label*='title'], #textbox", timeout=30000)
                await asyncio.sleep(2)

                # Check if reauth modal is present right away
                await self.check_and_handle_reauth(page, context)

                # Set Title
                title_box = page.locator("#textbox[aria-label*='title'], ytcp-mention-textbox[label*='Title'] #textbox").first
                if await title_box.count() > 0:
                    await title_box.click(force=True)
                    await page.keyboard.press("Meta+A")
                    await page.keyboard.press("Backspace")
                    await title_box.type(upload_title, delay=10)
                    logger.info("Filled Title: %s", upload_title)

                # Set Description
                desc_box = page.locator("#textbox[aria-label*='description'], ytcp-mention-textbox[label*='Description'] #textbox").first
                if await desc_box.count() > 0:
                    await desc_box.click(force=True)
                    await page.keyboard.press("Meta+A")
                    await page.keyboard.press("Backspace")
                    await desc_box.type(description, delay=5)
                    logger.info("Filled Description.")

                # Select 'No, it's not made for kids' (mandatory YouTube step)
                not_for_kids = page.locator("#not-made-for-kids-radio, tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").first
                if await not_for_kids.count() > 0:
                    await not_for_kids.click(force=True)
                    logger.info("Selected 'Not made for kids'")

                # Open 'Show more' to add tags
                show_more_btn = page.locator("#toggle-button:has-text('Show more'), button:has-text('Show more')").first
                if await show_more_btn.count() > 0:
                    try:
                        await show_more_btn.click(force=True)
                        await asyncio.sleep(1)
                        tags_input = page.locator("input[aria-label='Tags'], #tags-container input, #text-input[aria-label='Tags']").first
                        if await tags_input.count() > 0:
                            tags_csv = ",".join([t.replace("#", "") for t in tags[:15]])
                            await tags_input.type(tags_csv + ",", delay=10)
                            logger.info("Added tags: %s", tags_csv)
                    except Exception as tag_err:
                        logger.warning("Could not fill tags (non-fatal): %s", tag_err)

                # Check if YouTube Daily Upload Limit is reached
                daily_limit_msg = page.locator("text='Daily upload limit reached', [aria-label*='Daily upload limit reached']").first
                if await daily_limit_msg.count() > 0 and await daily_limit_msg.is_visible():
                    logger.critical("🛑 YOUTUBE DAILY UPLOAD LIMIT REACHED: Channel has hit its 24-hour upload cap. YouTube requires a one-time channel verification (phone/video ID) or waiting 24 hours to upload more videos.")
                    raise PermissionError("YouTube Daily Upload Limit Reached: Upload more videos daily after a one-time verification or wait 24 hours.")

                # Step through wizard to Visibility
                next_btn = page.locator("#next-button")
                for step_idx in range(4):
                    if await next_btn.is_visible() and await next_btn.is_enabled():
                        await next_btn.click(force=True)
                        logger.info("Clicked Next (step %d)", step_idx + 1)
                        await asyncio.sleep(2)
                        await self.check_and_handle_reauth(page, context)
                    elif await page.locator("text='Daily upload limit reached'").count() > 0:
                        raise PermissionError("YouTube Daily Upload Limit Reached: Upload more videos daily after a one-time verification or wait 24 hours.")

                # Jump to Visibility step badge directly if not already there
                public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
                if not (await public_radio.count() > 0 and await public_radio.is_visible()):
                    step_3 = page.locator("#step-badge-3, [id*='step-badge-3']").first
                    if await step_3.count() > 0 and await step_3.is_visible():
                        await step_3.click(force=True)
                        await asyncio.sleep(2)
                        await self.check_and_handle_reauth(page, context)

                # Set Visibility to Public
                if await public_radio.count() > 0:
                    await public_radio.click(force=True)
                    logger.info("Selected 'Public' visibility")
                else:
                    raise RuntimeError("Could not find or select 'Public' visibility radio button in YouTube Studio.")

                # Grab the generated YouTube Short link if displayed
                video_url = None
                link_elem = page.locator("a.ytcp-video-info, a[href*='youtu.be']").first
                if await link_elem.count() > 0:
                    video_url = await link_elem.get_attribute("href")
                    logger.info("Extracted YouTube video URL: %s", video_url)

                # Click Publish / Done
                done_btn = page.locator("#done-button, #publish-button, button:has-text('Publish')").first
                await done_btn.wait_for(state="visible", timeout=15000)
                if await done_btn.get_attribute("aria-disabled") == "true":
                    raise RuntimeError("YouTube Studio Publish button is disabled.")

                await done_btn.click(force=True)
                logger.info("Clicked Publish! Video is now finalizing on YouTube.")
                await asyncio.sleep(5)

                # Check for post-publish dialog dismissal
                close_btn = page.locator("ytcp-uploads-dialog ytcp-button#close-button, ytcp-uploads-still-processing-dialog ytcp-button#close-button, button:has-text('Close')").first
                if await close_btn.count() > 0 and await close_btn.is_visible():
                    # Extract URL from dialog if not found yet
                    post_link = page.locator("ytcp-uploads-dialog a[href*='youtu.be'], ytcp-uploads-still-processing-dialog a[href*='youtu.be']").first
                    if await post_link.count() > 0 and not video_url:
                        video_url = await post_link.get_attribute("href")
                    await close_btn.click(force=True)
                    logger.info("Dismissed post-publish dialog.")

                try:
                    await context.storage_state(path=str(BACKEND_DIR / "browser_data" / "storage_state.json"))
                    cookies = await context.cookies()
                    with open(self.cookies_file, "w") as f:
                        json.dump(cookies, f, indent=2)
                    logger.info("Persisted updated cookies and session state after upload.")
                except Exception as save_err:
                    logger.warning("Could not persist cookies: %s", save_err)

                return {
                    "success": True,
                    "title": upload_title,
                    "video_url": video_url,
                    "video_path": str(video_path),
                }

            except Exception as e:
                logger.error("Error during headless YouTube upload: %s", e)
                # Take debug screenshot in background if failed
                debug_shot = BACKEND_DIR / "browser_data" / "last_upload_error.png"
                try:
                    await page.screenshot(path=str(debug_shot))
                    logger.info("Saved error screenshot to: %s", debug_shot)
                except Exception:
                    pass
                raise e
            finally:
                await context.close()

    async def verify_video_on_youtube(self, expected_title: str) -> Dict[str, Any]:
        """
        Audits YouTube Studio Content completely headlessly to verify if an uploaded video
        is live, processed, and public on YouTube.
        Matches by title, extracts video ID, public YouTube Shorts URL, visibility, and status.
        """
        import re
        norm_target = re.sub(r'[^a-zA-Z0-9]', '', expected_title.lower().replace('#shorts', ''))
        
        async with async_playwright() as p:
            context = await self.get_context(p)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                logger.info("Auditing YouTube Studio Content to verify video: '%s'...", expected_title)
                content_urls = [
                    "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short",
                    "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/upload"
                ]
                
                for content_url in content_urls:
                    try:
                        await page.goto(content_url, timeout=35000, wait_until="domcontentloaded")
                        try:
                            await page.wait_for_selector("ytcp-video-row, ytcp-table", timeout=15000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                    except Exception as nav_err:
                        logger.warning("Notice on navigation to %s: %s", content_url, nav_err)

                    rows = page.locator("ytcp-video-row")
                    count = await rows.count()
                    
                    for i in range(count):
                        row = rows.nth(i)
                        title_el = row.locator("#video-title")
                        row_title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else ""
                        norm_row = re.sub(r'[^a-zA-Z0-9]', '', row_title.lower().replace('#shorts', ''))
                        
                        # Match titles
                        if norm_target in norm_row or norm_row in norm_target:
                            text = (await row.inner_text()).replace("\n", " | ")
                            
                            # Extract video ID
                            video_id = None
                            link_el = row.locator('a[href*="/video/"]').first
                            if await link_el.count() > 0:
                                href = await link_el.get_attribute("href")
                                m = re.search(r'/video/([^/]+)', href)
                                if m:
                                    video_id = m.group(1)
                                    
                            is_published = any(v in text for v in ["Public", "Published", "Unlisted"])
                            is_abandoned = any(v in text for v in ["Processing abandoned", "Draft", "Failed"])
                            is_processing = "Processing" in text and "abandoned" not in text

                            is_verified = is_published and not is_abandoned
                            youtube_url = f"https://www.youtube.com/shorts/{video_id}" if video_id else None

                            logger.info(
                                "Found match on Studio content: Title='%s', ID=%s, Published=%s, Abandoned=%s",
                                row_title, video_id, is_published, is_abandoned
                            )
                            return {
                                "verified": is_verified,
                                "video_id": video_id,
                                "youtube_url": youtube_url,
                                "title": row_title,
                                "status_text": text,
                                "is_published": is_published,
                                "is_abandoned": is_abandoned,
                                "is_processing": is_processing,
                                "found": True
                            }

                return {
                    "verified": False,
                    "found": False,
                    "reason": "video_not_found_in_studio_content",
                    "title": expected_title
                }
            except Exception as e:
                logger.error("Error verifying video on YouTube: %s", e)
                return {
                    "verified": False,
                    "found": False,
                    "error": str(e),
                    "reason": "verification_error"
                }
            finally:
                await context.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uploader = HeadlessYouTubeUploader(headless=True)
    res = asyncio.run(uploader.check_auth_status())
    print("Auth check result:", res)
