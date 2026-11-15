#!/usr/bin/env python3
"""
Database Migration & Title Cleanup Script for SupoClip.
Finds all clips in PostgreSQL with generic or duplicate titles,
and replaces each with a 100% unique, content-specific 3-7 word title
grounded in the clip's transcript dialogue and action reasoning.
"""

import asyncio
import difflib
import json
import logging
import re
import sys
import time
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.ai import AntigravityDirectModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TitleFixer]: %(message)s"
)
logger = logging.getLogger("TitleFixer")

GENERIC_OR_REPETITIVE_TITLES = {
    "watchhisfacewhenherealizes",
    "watchherfacewhensherealizes",
    "watchtheirfacewhentheyrealize",
    "thereisnowayhesaidthat",
    "thereisnowayshesaidthat",
    "thereisnowaytheysaidthat",
    "theexactsecondeverythingfellapart",
    "theexactmomentitfellapart",
    "livestreamhighlight",
    "highlightfromstreamer",
    "instantregretin4k",
    "waitforit",
    "hethoughthewassafeuntil",
    "shethoughtshewassafeuntil",
    "caughtin4kdoingtheworstthingpossible",
    "brostartedcelebrating2secondstooearly",
    "wentfrom200iqto0iqin3seconds",
    "themostunhingeddmintwitchhistory",
    "themostunhingedconfessionintwitchhistory",
    "broforgotthemicwasstillon",
    "herealizedhismistaketoolate",
    "sherealizedhermistaketoolate",
    "brocelebratedtwosecondstooearly",
    "hecompletelylosthismindlive",
    "hesaidthequietpartoutloud",
    "shesaidthequietpartoutloud",
    "frompurehypetocompletesilence",
    "thereisnowayheplayedthat",
    "thereisnowaysheplayedthat",
}

def normalize_title(t: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', (t or '').lower().replace('#shorts', ''))

def is_duplicate_or_similar(cand: str, existing_norm_set: set[str], existing_raw_list: list[str]) -> bool:
    norm = normalize_title(cand)
    if not norm or norm in existing_norm_set or norm in GENERIC_OR_REPETITIVE_TITLES:
        return True
    words = cand.split()
    if len(words) < 3 or len(words) > 8:
        return True
    for raw in existing_raw_list:
        norm_r = normalize_title(raw)
        if norm_r and difflib.SequenceMatcher(None, norm, norm_r).ratio() >= 0.70:
            return True
    return False

def procedural_unique_title(streamer: str, transcript: str, reasoning: str, existing_norm_set: set[str]) -> str:
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "about",
        "against", "between", "into", "through", "during", "before", "after", "above", "below",
        "from", "up", "down", "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "can", "could", "shall", "should", "will", "would", "may",
        "might", "must", "it", "its", "you", "your", "he", "she", "they", "we", "i", "me", "my",
        "this", "that", "what", "which", "who", "whom", "here", "there", "when", "where", "why",
        "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such",
        "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just", "like",
        "oh", "bro", "dude", "okay", "yeah", "gonna", "wanna", "gosh", "omg", "uh", "um", "said",
        "think", "know", "going", "really", "cant", "dont", "told"
    }
    raw_source = f"{transcript} {reasoning}"
    tokens = [re.sub(r'[^a-zA-Z]', '', w) for w in raw_source.split()]
    meaningful = [w.capitalize() for w in tokens if len(w) > 3 and w.lower() not in stop_words]
    clean_streamer = streamer.capitalize() if streamer and streamer.lower() != "none" else "Streamer"

    if len(meaningful) >= 4:
        cand = f"When {clean_streamer} Faced {meaningful[0]} {meaningful[1]}"
    elif len(meaningful) >= 2:
        cand = f"{clean_streamer} Reacts To {meaningful[0]} {meaningful[1]}"
    elif len(meaningful) == 1:
        cand = f"{clean_streamer} Shocked By {meaningful[0]}"
    else:
        cand = f"{clean_streamer} Unfiltered Moment"

    if normalize_title(cand) in existing_norm_set:
        cand = f"{cand} #{int(time.time() * 1000) % 10000}"
    return cand

async def generate_ai_title(
    agent: AntigravityDirectModel,
    streamer: str,
    transcript: str,
    reasoning: str,
    existing_norm_set: set[str],
    existing_raw_list: list[str],
) -> str:
    clean_streamer = streamer if streamer and streamer.lower() != "none" else "Streamer"
    recent_clause = "\n".join(f"- {t}" for t in existing_raw_list[-20:])
    prompt = f"""You are an elite YouTube Shorts title strategist.
Generate 5 completely UNIQUE, viral titles (3 to 7 words only) for this specific stream clip.

STREAMER: {clean_streamer}
CLIP TRANSCRIPT / WHAT WAS SAID:
"{transcript[:500]}"

WHAT HAPPENED / REASONING:
"{reasoning[:250]}"

RULES:
1. STRICTLY 3 TO 7 WORDS ONLY.
2. Must specifically reflect the dialogue, topic, or reaction in THIS clip.
3. Plain text only. NO quotes, NO hashtags, NO emojis.
4. FORBIDDEN to copy or resemble any generic templates or recently used titles:
{recent_clause}

Respond ONLY with a JSON array of 5 unique title strings:
["Title Option 1", "Title Option 2", "Title Option 3", "Title Option 4", "Title Option 5"]
"""
    try:
        resp = await agent.request(prompt)
        raw_text = ""
        for p in getattr(resp, "parts", []):
            if hasattr(p, "content") and p.content:
                raw_text = p.content
                break
        if not raw_text:
            raw_text = str(resp)

        match = re.search(r"\[\s*\".*\"\s*\]", raw_text, re.DOTALL)
        if match:
            candidates = json.loads(match.group(0))
            for cand in candidates:
                cand_clean = cand.strip().strip('"').strip("'")
                if not is_duplicate_or_similar(cand_clean, existing_norm_set, existing_raw_list) and 3 <= len(cand_clean.split()) <= 8:
                    return cand_clean
    except Exception as e:
        logger.debug("AI title generation error: %s", e)

    return procedural_unique_title(streamer, transcript, reasoning, existing_norm_set)

async def main():
    logger.info("Starting Database Title Fixer & Uniqueness Enforcement...")
    agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")

    async with AsyncSessionLocal() as db:
        # Step 1: Identify all unique titles and count duplicates
        all_clips_res = await db.execute(text("""
            SELECT id, hook_title, text, reasoning, workflow_meta, created_at
            FROM generated_clips
            ORDER BY created_at ASC
        """))
        clips = all_clips_res.fetchall()
        logger.info("Loaded %d total clips from database.", len(clips))

        # Build existing clean titles set (titles that appear only ONCE and are not generic)
        title_counts = {}
        for c in clips:
            t = (c[1] or "").strip()
            title_counts[t] = title_counts.get(t, 0) + 1

        seen_norm_set = set()
        seen_raw_list = []
        clips_to_fix = []

        for c in clips:
            clip_id, raw_title, transcript, reasoning, wf_meta, created_at = c
            t = (raw_title or "").strip()
            norm = normalize_title(t)
            is_generic = norm in GENERIC_OR_REPETITIVE_TITLES
            is_dup = title_counts.get(t, 0) > 1

            if is_dup or is_generic or not t or len(t.split()) < 3:
                # Needs fix (keep the first occurrence ONLY if it is not generic and is > 3 words)
                if not is_generic and norm not in seen_norm_set and len(t.split()) >= 3:
                    seen_norm_set.add(norm)
                    seen_raw_list.append(t)
                else:
                    clips_to_fix.append(c)
            else:
                seen_norm_set.add(norm)
                seen_raw_list.append(t)

        logger.info(
            "Found %d clips with duplicate or generic titles that need fixing (%d titles already unique).",
            len(clips_to_fix), len(seen_raw_list)
        )

        if not clips_to_fix:
            logger.info("All titles in database are already unique! Nothing to fix.")
            return

        # Process each clip needing a fix in batches
        fixed_count = 0
        batch_size = 5
        for i in range(0, len(clips_to_fix), batch_size):
            batch = clips_to_fix[i:i + batch_size]
            tasks = []
            for item in batch:
                clip_id, old_title, transcript, reasoning, wf_meta, created_at = item
                streamer = (wf_meta or {}).get("streamer") or "Streamer"
                tasks.append(
                    generate_ai_title(
                        agent=agent,
                        streamer=streamer,
                        transcript=transcript or "",
                        reasoning=reasoning or "",
                        existing_norm_set=seen_norm_set,
                        existing_raw_list=seen_raw_list,
                    )
                )

            new_titles = await asyncio.gather(*tasks)

            for item, new_title in zip(batch, new_titles):
                clip_id, old_title, transcript, reasoning, wf_meta, created_at = item
                clean_new_title = new_title.strip()
                norm_new = normalize_title(clean_new_title)

                seen_norm_set.add(norm_new)
                seen_raw_list.append(clean_new_title)

                # Update DB
                updated_meta = dict(wf_meta or {})
                if updated_meta.get("uploaded") != "true":
                    updated_meta["youtube_title"] = clean_new_title

                await db.execute(
                    text("""
                        UPDATE generated_clips
                        SET hook_title = :new_title,
                            workflow_meta = CAST(:meta AS jsonb)
                        WHERE id = :id
                    """),
                    {
                        "new_title": clean_new_title,
                        "meta": json.dumps(updated_meta),
                        "id": clip_id,
                    }
                )
                fixed_count += 1
                logger.info(
                    "[%3d/%3d] Fixed clip %s:\n  Old: '%s'\n  New: '%s'",
                    fixed_count, len(clips_to_fix), str(clip_id)[:8], old_title, clean_new_title
                )

            await db.commit()
            # Brief pause to avoid rate limiting
            await asyncio.sleep(0.5)

        logger.info("Successfully updated %d clips with completely unique titles!", fixed_count)

        # Verification query
        dup_check = await db.execute(text("""
            SELECT hook_title, COUNT(*) 
            FROM generated_clips 
            GROUP BY hook_title 
            HAVING COUNT(*) > 1
        """))
        remaining_dups = dup_check.fetchall()
        if remaining_dups:
            logger.warning("Remaining duplicates found: %s", remaining_dups)
        else:
            logger.info("✅ VERIFIED: 0 duplicate titles remaining in PostgreSQL database!")

if __name__ == "__main__":
    asyncio.run(main())
