#!/usr/bin/env python3
"""
High-throughput batch dataset collector for 1,000 GTA 5 YouTube Shorts.
Uses YouTube's native 'under 4 minutes' & recent upload date filter (sp=EgQQARgB).
Deduplicates IDs, captures full metadata, and outputs to gta5_dataset_1000.jsonl.
"""

import sys
import json
import time
import random
from pathlib import Path
import yt_dlp

STUDY_DIR = Path("/Users/luv/.gemini/antigravity/scratch/supoclip/research/gta_study")
STUDY_DIR.mkdir(parents=True, exist_ok=True)
DATASET_FILE = STUDY_DIR / "gta5_dataset_1000.jsonl"
PROGRESS_FILE = STUDY_DIR / "fetch_progress.json"

QUERIES = [
    {"query": "GTA+5+streamer+funny+moments", "category": "streamer_comedy_banter"},
    {"query": "xQc+GTA+RP+clips+shorts", "category": "xqc_heists_malding"},
    {"query": "IShowSpeed+GTA+5+shorts", "category": "speed_high_energy_reactions"},
    {"query": "Kai+Cenat+GTA+5+RP+shorts", "category": "kai_social_dynamics"},
    {"query": "GTA+RP+NoPixel+funny+moments+shorts", "category": "nopixel_roleplay_chaos"},
    {"query": "GTA+5+police+chase+streamer+escape+shorts", "category": "high_stakes_escapes"},
    {"query": "GTA+5+insane+stunts+fails+shorts", "category": "stunts_ragdoll_fails"},
    {"query": "GTA+5+plot+twist+betrayal+streamer+shorts", "category": "plot_twists_betrayals"},
    {"query": "GTA+5+instant+karma+rage+shorts", "category": "instant_karma_rage"},
    {"query": "GTA+5+streamer+reacts+shorts", "category": "streamer_reactions"},
    {"query": "GTA+5+mods+heist+challenge+shorts", "category": "sandbox_mod_heists"},
    {"query": "GTA+5+unhinged+NPC+moments+shorts", "category": "npc_ai_absurdity"},
]

def load_existing():
    existing_ids = set()
    records = []
    if DATASET_FILE.exists():
        with open(DATASET_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        d = json.loads(line)
                        if "id" in d:
                            existing_ids.add(d["id"])
                            records.append(d)
                    except Exception:
                        pass
    return existing_ids, records

def run():
    existing_ids, records = load_existing()
    print(f"Loaded {len(records)} existing unique clips from {DATASET_FILE}")

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
        "ignoreerrors": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for idx, item in enumerate(QUERIES, 1):
            if len(records) >= 1000:
                print("Target of 1000 unique clips reached!")
                break

            q = item["query"]
            cat = item["category"]
            search_url = f"https://www.youtube.com/results?search_query={q}&sp=EgQQARgB"
            print(f"\n[{idx}/{len(QUERIES)}] Fetching batch '{cat}'...")

            try:
                res = ydl.extract_info(search_url, download=False)
                entries = res.get("entries") or []
                batch_added = 0

                for e in entries:
                    if not e or not isinstance(e, dict):
                        continue
                    vid_id = e.get("id")
                    if not vid_id or vid_id in existing_ids:
                        continue

                    duration = e.get("duration") or 0
                    # Standard YouTube Short is <= 60s (allow up to 65s for intro/outro padding)
                    if duration > 65:
                        continue

                    title = e.get("title") or ""
                    if not title or len(title.strip()) < 3:
                        continue

                    record = {
                        "id": vid_id,
                        "title": title,
                        "url": f"https://www.youtube.com/shorts/{vid_id}",
                        "duration": duration,
                        "view_count": e.get("view_count") or 0,
                        "channel": e.get("channel") or e.get("uploader") or "",
                        "category": cat,
                        "search_query": q.replace("+", " "),
                        "session_idx": idx,
                    }

                    existing_ids.add(vid_id)
                    records.append(record)
                    batch_added += 1

                    with open(DATASET_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record) + "\n")

                    if len(records) >= 1000:
                        break

                print(f"Session {idx} added {batch_added} new Shorts. Total unique records: {len(records)}/1000")

                with open(PROGRESS_FILE, "w") as pf:
                    json.dump({"completed_sessions": idx, "total_records": len(records)}, pf, indent=2)

                delay = random.uniform(2.5, 4.5)
                print(f"Polite anti-detection delay: {delay:.1f}s...")
                time.sleep(delay)

            except Exception as err:
                print(f"Session {idx} error: {err}")
                time.sleep(3)

    print(f"\n==================================================")
    print(f"FINAL DATASET SIZE: {len(records)} unique GTA 5 YouTube Shorts")
    print(f"Location: {DATASET_FILE}")
    print(f"==================================================")

if __name__ == "__main__":
    run()
