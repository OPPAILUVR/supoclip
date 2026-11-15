#!/usr/bin/env python3
"""
CLI tool to clean metadata, inject viral SEO tags, and prepare clips for YouTube Shorts uploading.
"""

import sys
import os
import argparse
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.video_metadata import strip_and_embed_video_metadata, get_streamer_tags

def prepare_clip(video_path_str: str, title: str, streamer_name: str):
    video_path = Path(video_path_str).resolve()
    if not video_path.exists():
        print(f"Error: File not found: {video_path}")
        return False

    tags = get_streamer_tags(streamer_name)
    tags_str = " ".join(tags)
    
    description = f"""{title}

Streamer: {streamer_name}
Clipped live using SupoClip AI.

{tags_str}
"""

    print(f"--- PREPARING CLIP FOR YOUTUBE ---")
    print(f"Target Video: {video_path.name}")
    print(f"Title: {title}")
    print(f"Streamer: {streamer_name}")
    print(f"Tags: {tags_str}")
    
    # 1. Strip and embed metadata
    success = strip_and_embed_video_metadata(
        video_path=video_path,
        title=title,
        streamer_name=streamer_name,
        custom_tags=tags,
        description=description
    )
    
    if success:
        print(f"\n[SUCCESS] Old encoder metadata stripped, fresh YouTube SEO metadata embedded directly into video!")
        manifest = {
            "file": str(video_path),
            "title": title,
            "description": description,
            "tags": tags,
            "streamer": streamer_name,
            "status": "ready_for_upload"
        }
        manifest_file = video_path.with_suffix(".youtube_upload.json")
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"Upload Manifest saved to: {manifest_file}")
        return True
    else:
        print("[ERROR] Failed to embed metadata.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean and embed YouTube metadata into a clip.")
    parser.add_argument("video_path", help="Path to the MP4 clip")
    parser.add_argument("--title", required=True, help="Click-forcing viral title")
    parser.add_argument("--streamer", default="Streamer", help="Streamer name")
    
    args = parser.parse_args()
    prepare_clip(args.video_path, args.title, args.streamer)
