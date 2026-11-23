import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from src.services.youtube_headless_uploader import HeadlessYouTubeUploader

async def main():
    uploader = HeadlessYouTubeUploader(headless=True)
    async with async_playwright() as p:
        ctx = await uploader.get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        for tab_name, tab_url in [("Videos", "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/upload"), ("Shorts", "https://studio.youtube.com/channel/UCfSSIQbWKw7Pl6jCdHD_rxg/videos/short")]:
            print(f"\n==========================================")
            print(f"--- Checking {tab_name} Tab ({tab_url}) ---")
            await page.goto(tab_url, timeout=60000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            # Extract video items cleanly using standard JS
            data = await page.evaluate("""() => {
                const rows = document.querySelectorAll("ytcp-video-row");
                const items = [];
                rows.forEach(r => {
                    const titleEl = r.querySelector("#video-title");
                    const textContent = r.innerText || "";
                    const isDraft = textContent.toLowerCase().includes("draft");
                    items.push({
                        title: titleEl ? titleEl.innerText.trim() : "Untitled",
                        text: textContent.replace(/\\n+/g, " | ").substring(0, 200),
                        is_draft: isDraft
                    });
                });
                
                // Get table footer pagination text
                const footer = document.querySelector("ytcp-table-footer")?.innerText || "";
                return { items, footer };
            }""")
            
            total_items = data['items']
            drafts = [it for it in total_items if it['is_draft']]
            print(f"Table Footer: {data['footer'].replace(chr(10), ' | ')}")
            print(f"Total rows on page: {len(total_items)}")
            print(f"Total drafts visible: {len(drafts)}")
            print("\nDrafts breakdown:")
            for idx, it in enumerate(drafts[:25]):
                print(f"  [{idx+1}] {it['title']}  :::  {it['text'][:120]}")
                
            tab_shot = f"/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/studio_{tab_name.lower()}_tab.png"
            await page.screenshot(path=tab_shot)
            print(f"Saved {tab_name} screenshot to {tab_shot}")

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
