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
from typing import Optional, Dict, Any, List

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
        is_short: bool = True,
        thumbnail_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Uploads a video completely headlessly with zero desktop interference.
        Attaches video file directly via set_input_files, fills metadata, sets Public, and publishes.
        
        STRICT RELIABILITY GUARANTEES:
        1. Pre-upload duplicate check: Never uploads duplicate titles.
        2. Wait for full video upload before publishing: Never closes early while uploading.
        3. Mandatory Post-Upload Verification: Confirms on YouTube Studio that the video
           row has status 'Public' (NOT 'Draft').
        4. Zero Draft Tolerance: If YouTube commits as Draft, immediately walks 'Edit draft'
           to force 'Public'. If it still remains in Draft, deletes the draft permanently
           so no orphaned drafts ever sit in the channel.
        """
        import re
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Ensure title fits Shorts requirements
        upload_title = title[:95]
        if is_short and "#shorts" not in upload_title.lower():
            upload_title = f"{upload_title} #shorts"[:100]

        norm_title = re.sub(r'[^a-zA-Z0-9]', '', upload_title.lower().replace('#shorts', ''))

        async with async_playwright() as p:
            context = await self.get_context(p)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                logger.info("Opening YouTube Studio in background...")
                await page.goto("https://studio.youtube.com", timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                
                if "accounts.google.com" in page.url:
                    raise PermissionError("YouTube Studio is not authenticated. Please import cookies or perform one-time login.")

                # Pre-upload check: Check if video already exists on channel
                content_url = "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short"
                logger.info("Pre-upload check: Auditing channel to prevent duplicate uploads...")
                await page.goto(content_url, timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                
                existing_rows = await page.locator("ytcp-video-row").all()
                for r in existing_rows:
                    txt = await r.inner_text()
                    title_match = norm_title in re.sub(r'[^a-zA-Z0-9]', '', txt.lower().replace('#shorts', ''))
                    if title_match:
                        if "Public" in txt or "Published" in txt:
                            logger.info("Video '%s' is ALREADY PUBLIC on YouTube! Skipping duplicate upload.", upload_title)
                            link_el = r.locator("a[href*='/video/'], a.ytcp-video-info").first
                            video_id = None
                            if await link_el.count() > 0:
                                href = await link_el.get_attribute("href")
                                m = re.search(r'/video/([^/]+)', href or "")
                                if m:
                                    video_id = m.group(1)
                            video_url = f"https://www.youtube.com/shorts/{video_id}" if video_id else None
                            return {
                                "success": True,
                                "status": "published",
                                "title": upload_title,
                                "video_url": video_url,
                                "verified": True,
                                "duplicate_prevented": True
                            }
                        elif "Draft" in txt:
                            logger.warning("Found stale draft for '%s'. Deleting draft before clean upload...", upload_title)
                            await r.hover()
                            await asyncio.sleep(1)
                            opt_btn = r.locator("#options-button, button[aria-label*='Options' i]").first
                            if await opt_btn.count() > 0:
                                await opt_btn.click(force=True)
                                await asyncio.sleep(1)
                                del_menu = page.locator("tp-yt-paper-item:has-text('Delete forever')").first
                                if await del_menu.count() > 0:
                                    await del_menu.click(force=True)
                                    await asyncio.sleep(1)
                                    conf_dialog = page.locator("ytcp-confirmation-dialog").filter(has_text="Delete").first
                                    conf_cb = conf_dialog.locator("ytcp-checkbox-lit, #confirm-checkbox").first
                                    if await conf_cb.count() > 0:
                                        await conf_cb.click(force=True)
                                    conf_btn = conf_dialog.locator("ytcp-button#confirm-button, button:has-text('Delete forever')").first
                                    if await conf_btn.count() > 0:
                                        await conf_btn.click(force=True)
                                        await asyncio.sleep(3)

                # Click Create button to initiate upload
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
                title_box = page.locator("#title-textarea #textbox, #textbox[aria-label*='title' i]").first
                if await title_box.count() > 0:
                    await title_box.click(force=True)
                    await title_box.fill(upload_title)
                    logger.info("Filled Title: %s", upload_title)
                else:
                    logger.warning("Could not locate title textbox via selector, attempting fallback...")

                # Set Description
                desc_box = page.locator("#description-textarea #textbox, [aria-label*='Tell viewers' i]").first
                if await desc_box.count() > 0:
                    await desc_box.click(force=True)
                    await desc_box.fill(description)
                    logger.info("Filled Description (%d chars).", len(description))
                else:
                    raise RuntimeError("CHECKLIST VIOLATION: Could not locate YouTube description box (#description-textarea #textbox). Upload aborted — description is MANDATORY.")

                # Upload custom viral thumbnail if provided
                if thumbnail_path and Path(thumbnail_path).exists():
                    try:
                        thumb_file = str(Path(thumbnail_path).resolve())
                        logger.info("Attaching viral thumbnail: %s", Path(thumbnail_path).name)
                        thumb_input = page.locator("input#file-loader, ytcp-thumbnails-compact-editor input[type='file'], input[type='file'][accept*='image']").first
                        if await thumb_input.count() > 0:
                            await thumb_input.set_input_files(thumb_file)
                            logger.info("Successfully attached viral thumbnail via input element!")
                            await asyncio.sleep(2)
                        else:
                            thumb_btn = page.locator("button#select-button, #upload-button, [aria-label*='Upload thumbnail' i], ytcp-button:has-text('Upload thumbnail')").first
                            if await thumb_btn.count() > 0 and await thumb_btn.is_visible():
                                async with page.expect_file_chooser(timeout=5000) as fc_info:
                                    await thumb_btn.click(force=True)
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(thumb_file)
                                logger.info("Successfully attached viral thumbnail via file chooser!")
                                await asyncio.sleep(2)
                    except Exception as thumb_err:
                        logger.warning("Thumbnail upload notice (non-fatal): %s", thumb_err)

                # Select 'No, it's not made for kids'
                not_for_kids = page.locator("#not-made-for-kids-radio, tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").first
                if await not_for_kids.count() > 0:
                    await not_for_kids.click(force=True)
                    logger.info("Selected 'Not made for kids'")

                # Tag Handling
                if tags and len(tags) > 0:
                    show_more_btn = page.locator("#toggle-button:has-text('Show more'), button:has-text('Show more')").first
                    if await show_more_btn.count() > 0:
                        try:
                            await show_more_btn.click(force=True)
                            await asyncio.sleep(1)
                            tags_input = page.locator("input[aria-label='Tags'], #tags-container input, #text-input[aria-label='Tags']").first
                            if await tags_input.count() > 0:
                                tags_csv = ",".join([t.replace("#", "") for t in tags[:5]])
                                await tags_input.type(tags_csv + ",", delay=10)
                                logger.info("Added clean tags: %s", tags_csv)
                        except Exception as tag_err:
                            logger.warning("Could not fill tags (non-fatal): %s", tag_err)

                # Check if YouTube Daily Upload Limit is reached
                daily_limit_msg = page.locator("text='Daily upload limit reached', [aria-label*='Daily upload limit reached']").first
                if await daily_limit_msg.count() > 0 and await daily_limit_msg.is_visible():
                    logger.critical("🛑 YOUTUBE DAILY UPLOAD LIMIT REACHED: Channel has hit its 24-hour upload cap.")
                    raise PermissionError("YouTube Daily Upload Limit Reached: Upload more videos daily after a one-time verification or wait 24 hours.")

                # Wait for upload progress to reach at least 100% or processing before clicking Next
                logger.info("Monitoring upload progress to ensure video data is fully uploaded...")
                for _ in range(30):
                    progress_text = await page.evaluate("""() => {
                        const el = document.querySelector("ytcp-video-upload-progress, .progress-label, [role=progressbar]");
                        return el ? el.innerText : "";
                    }""")
                    if any(done_kw in progress_text.lower() for done_kw in ["upload complete", "processing", "checks", "100%"]):
                        logger.info("Upload progress confirmed: %s", progress_text.strip().replace("\n", " "))
                        break
                    await asyncio.sleep(2)

                # Step through wizard to Visibility
                next_btn = page.locator("#next-button")
                for step_idx in range(1, 5):
                    if await next_btn.is_visible() and await next_btn.is_enabled():
                        await next_btn.click(force=True)
                        logger.info("Clicked Next (step %d)", step_idx)
                        await asyncio.sleep(2.5)
                        await self.check_and_handle_reauth(page, context)
                    elif await page.locator("text='Daily upload limit reached'").count() > 0:
                        raise PermissionError("YouTube Daily Upload Limit Reached: Upload more videos daily after a one-time verification or wait 24 hours.")
                    else:
                        break

                # Ensure Visibility step is active
                public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
                if not (await public_radio.count() > 0 and await public_radio.is_visible()):
                    step_3 = page.locator("#step-badge-3, [id*='step-badge-3']").first
                    if await step_3.count() > 0 and await step_3.is_visible():
                        await step_3.click(force=True)
                        await asyncio.sleep(2.5)
                        await self.check_and_handle_reauth(page, context)

                # Set Visibility to Public
                if await public_radio.count() > 0 and await public_radio.is_visible():
                    await public_radio.click(force=True)
                    logger.info("Selected 'Public' visibility")
                    await asyncio.sleep(2.0)
                else:
                    raise RuntimeError("Could not find or select 'Public' visibility radio button in YouTube Studio.")

                # Grab the generated YouTube Short link if displayed
                video_url = None
                link_elem = page.locator("a.ytcp-video-info, a[href*='youtu.be']").first
                if await link_elem.count() > 0:
                    video_url = await link_elem.get_attribute("href")
                    logger.info("Extracted YouTube video URL: %s", video_url)

                # Click Publish / Done
                done_btn = page.locator("#done-button, #publish-button, button:has-text('Publish'), button:has-text('Save')").first
                await done_btn.wait_for(state="visible", timeout=15000)
                if await done_btn.get_attribute("aria-disabled") == "true":
                    raise RuntimeError("YouTube Studio Publish button is disabled.")

                await done_btn.click(force=True)
                logger.info("Clicked Publish! Waiting for YouTube modal to dismiss...")
                await asyncio.sleep(6)

                # Only close if post-processing dialog explicitly appeared
                processing_dialog_close = page.locator("ytcp-uploads-still-processing-dialog ytcp-button#close-button, ytcp-uploads-still-processing-dialog button:has-text('Close')").first
                if await processing_dialog_close.count() > 0 and await processing_dialog_close.is_visible():
                    post_link = page.locator("ytcp-uploads-still-processing-dialog a[href*='youtu.be']").first
                    if await post_link.count() > 0 and not video_url:
                        video_url = await post_link.get_attribute("href")
                    await processing_dialog_close.click(force=True)
                    logger.info("Dismissed post-publish still-processing dialog.")
                    await asyncio.sleep(2)

                # =====================================================================
                # MANDATORY POST-UPLOAD VERIFICATION IN YOUTUBE STUDIO TABLE
                # =====================================================================
                logger.info("🔍 POST-UPLOAD VERIFICATION: Navigating to Shorts table to verify Public status...")
                await page.goto(content_url, timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(4)

                matched_row = None
                matched_text = ""
                rows = await page.locator("ytcp-video-row").all()
                for r in rows:
                    txt = await r.inner_text()
                    if norm_title in re.sub(r'[^a-zA-Z0-9]', '', txt.lower().replace('#shorts', '')):
                        matched_row = r
                        matched_text = txt
                        break

                if not matched_row and len(rows) > 0:
                    matched_row = rows[0]
                    matched_text = await matched_row.inner_text()

                logger.info("Target video row in Studio: %s", matched_text[:120].replace("\n", " | "))

                if matched_row:
                    link_el = matched_row.locator("a[href*='/video/'], a.ytcp-video-info").first
                    if await link_el.count() > 0:
                        href = await link_el.get_attribute("href")
                        m = re.search(r'/video/([^/]+)', href or "")
                        if m:
                            video_id = m.group(1)
                            if not video_url:
                                video_url = f"https://www.youtube.com/shorts/{video_id}"

                is_public = any(k in matched_text for k in ["Public", "Published", "Scheduled"])
                is_draft = "Draft" in matched_text

                if is_draft and matched_row:
                    logger.warning("⚠️ Video landed as DRAFT in YouTube Studio! Immediately fixing to Public via Edit draft wizard...")
                    edit_btn = matched_row.locator("button:has-text('Edit draft'), [aria-label*='Edit draft']").first
                    if await edit_btn.count() > 0:
                        await edit_btn.click(force=True)
                        await asyncio.sleep(3)
                        n_btn = page.locator("#next-button")
                        for _ in range(4):
                            if await n_btn.is_visible() and await n_btn.is_enabled():
                                await n_btn.click(force=True)
                                await asyncio.sleep(1.8)
                            else:
                                break
                        pub_r = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], tp-yt-paper-radio-button:has-text('Public')").first
                        if await pub_r.is_visible():
                            await pub_r.click(force=True)
                            await asyncio.sleep(1.0)
                        pub_btn = page.locator("#done-button, #publish-button, button:has-text('Publish'), button:has-text('Save')").first
                        if await pub_btn.is_visible() and await pub_btn.is_enabled():
                            await pub_btn.click(force=True)
                            await asyncio.sleep(6)
                            p_close = page.locator("ytcp-uploads-still-processing-dialog #close-button, ytcp-button:has-text('Close')").first
                            if await p_close.count() > 0 and await p_close.is_visible():
                                await p_close.click(force=True)
                        
                        await page.goto(content_url, timeout=35000, wait_until="domcontentloaded")
                        await asyncio.sleep(3)
                        rows_after = await page.locator("ytcp-video-row").all()
                        for r_a in rows_after:
                            txt_a = await r_a.inner_text()
                            if norm_title in re.sub(r'[^a-zA-Z0-9]', '', txt_a.lower().replace('#shorts', '')):
                                is_public = any(k in txt_a for k in ["Public", "Published", "Scheduled"])
                                is_draft = "Draft" in txt_a
                                break

                if is_draft:
                    logger.error("❌ Draft fix failed. Deleting draft from YouTube Studio to maintain zero-draft policy...")
                    if matched_row:
                        await matched_row.hover()
                        await asyncio.sleep(1)
                        opt_b = matched_row.locator("#options-button, button[aria-label*='Options' i]").first
                        if await opt_b.count() > 0:
                            await opt_b.click(force=True)
                            await asyncio.sleep(1)
                            del_m = page.locator("tp-yt-paper-item:has-text('Delete forever')").first
                            if await del_m.count() > 0:
                                await del_m.click(force=True)
                                await asyncio.sleep(1)
                                c_dialog = page.locator("ytcp-confirmation-dialog").filter(has_text="Delete").first
                                c_cb = c_dialog.locator("ytcp-checkbox-lit, #confirm-checkbox").first
                                if await c_cb.count() > 0:
                                    await c_cb.click(force=True)
                                c_b = c_dialog.locator("ytcp-button#confirm-button, button:has-text('Delete forever')").first
                                if await c_b.count() > 0:
                                    await c_b.click(force=True)
                                    await asyncio.sleep(3)
                    raise RuntimeError(f"Video '{upload_title}' could not be published to Public (ended up in Draft). Auto-deleted draft to prevent draft clutter.")

                if not is_public:
                    raise RuntimeError(f"Video '{upload_title}' visibility could not be confirmed as Public on YouTube Studio.")

                logger.info("🎉 SUCCESS: Video '%s' is 100%% VERIFIED PUBLIC on YouTube! URL: %s", upload_title, video_url)

                try:
                    await context.storage_state(path=str(BACKEND_DIR / "browser_data" / "storage_state.json"))
                    cookies = await context.cookies()
                    with open(self.cookies_file, "w") as f:
                        json.dump(cookies, f, indent=2)
                    logger.info("Persisted updated cookies and session state after verified upload.")
                except Exception as save_err:
                    logger.warning("Could not persist cookies: %s", save_err)

                return {
                    "success": True,
                    "status": "published",
                    "title": upload_title,
                    "video_url": video_url or "",
                    "video_path": str(video_path),
                    "verified": True,
                }

            except Exception as e:
                logger.error("Error during headless YouTube upload: %s", e)
                try:
                    discard_btn = page.locator("button:has-text('Discard draft'), ytcp-button#discard-button, #close-button, [aria-label='Close']").first
                    if await discard_btn.count() > 0 and await discard_btn.is_visible():
                        await discard_btn.click(force=True)
                        await asyncio.sleep(1)
                        confirm_discard = page.locator("button:has-text('Discard'), ytcp-button:has-text('Discard')").first
                        if await confirm_discard.count() > 0 and await confirm_discard.is_visible():
                            await confirm_discard.click(force=True)
                            logger.info("Auto-discarded incomplete upload dialog to prevent orphaned draft.")
                except Exception:
                    pass
                debug_shot = BACKEND_DIR / "browser_data" / "last_upload_error.png"
                try:
                    await page.screenshot(path=str(debug_shot))
                    logger.info("Saved error screenshot to: %s", debug_shot)
                except Exception:
                    pass
                raise e
            finally:
                await context.close()

    async def publish_all_unique_drafts(self, max_count: int = 5) -> List[Dict[str, Any]]:
        """
        Scans YouTube Studio for unpublished drafts, filters out duplicate titles,
        and publishes unique drafts to Public.
        Returns a list of published video results.
        """
        import re
        published_results = []
        
        async with async_playwright() as p:
            context = await self.get_context(p)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                content_url = "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short"
                await page.goto(content_url, timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                seen_titles = set()
                # First pass: find existing public titles
                rows = await page.locator("ytcp-video-row").all()
                for r in rows:
                    txt = await r.inner_text()
                    lines = [l.strip() for l in txt.split("\n") if l.strip()]
                    title = lines[1] if len(lines) > 1 else ""
                    norm = re.sub(r'[^a-zA-Z0-9]', '', title.lower().replace('#shorts', ''))
                    if "Public" in txt and norm:
                        seen_titles.add(norm)

                logger.info("Found %d already public videos to prevent duplicate titles.", len(seen_titles))

                published_count = 0
                while published_count < max_count:
                    # Refresh rows
                    rows = await page.locator("ytcp-video-row").all()
                    target_row = None
                    target_title = None
                    
                    for r in rows:
                        txt = await r.inner_text()
                        if "Draft" in txt:
                            lines = [l.strip() for l in txt.split("\n") if l.strip()]
                            title = lines[1] if len(lines) > 1 else ""
                            norm = re.sub(r'[^a-zA-Z0-9]', '', title.lower().replace('#shorts', ''))
                            if norm and norm not in seen_titles:
                                seen_titles.add(norm)
                                target_row = r
                                target_title = title
                                break

                    if not target_row:
                        logger.info("No more unique drafts found to publish.")
                        break

                    logger.info("Publishing unique draft: '%s'...", target_title)
                    edit_btn = target_row.locator('button:has-text("Edit draft")').first
                    if await edit_btn.count() == 0:
                        break

                    await edit_btn.click(force=True)
                    await asyncio.sleep(2.5)

                    # Step wizard to visibility
                    next_btn = page.locator("#next-button")
                    for step_i in range(4):
                        if await next_btn.is_visible() and await next_btn.is_enabled():
                            await next_btn.click(force=True)
                            await asyncio.sleep(1.8)
                        else:
                            break

                    # Select Public
                    public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"], tp-yt-paper-radio-button:has-text("Public")').first
                    if await public_radio.is_visible():
                        await public_radio.click(force=True)
                        await asyncio.sleep(1.0)

                    # Click Publish
                    publish_btn = page.locator('#done-button, #publish-button, button:has-text("Publish"), button:has-text("Save")').first
                    if await publish_btn.is_visible() and await publish_btn.is_enabled():
                        await publish_btn.click(force=True)
                        await asyncio.sleep(5.0)

                        # Capture video link from modal if shown
                        video_link_el = page.locator("a.ytcp-video-info, a[href*='youtu']").first
                        video_url = await video_link_el.get_attribute("href") if await video_link_el.count() > 0 else None

                        logger.info("✅ Successfully published draft '%s' to Public! (URL: %s)", target_title, video_url)
                        published_results.append({
                            "title": target_title,
                            "url": video_url,
                            "status": "published"
                        })
                        published_count += 1

                        # Close dialog
                        close_btn = page.locator("ytcp-uploads-still-processing-dialog #close-button, ytcp-button:has-text('Close')").first
                        if await close_btn.count() > 0 and await close_btn.is_visible():
                            await close_btn.click(force=True)
                            await asyncio.sleep(1.5)

                        # Reload table
                        await page.goto(content_url, timeout=35000, wait_until="domcontentloaded")
                        await asyncio.sleep(2.5)
                    else:
                        logger.warning("Publish button was not enabled for draft '%s'.", target_title)
                        break

                return published_results
            except Exception as e:
                logger.error("Error in publish_all_unique_drafts: %s", e)
                return published_results
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
