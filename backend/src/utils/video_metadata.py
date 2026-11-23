import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

import re

STREAMER_TAGS = {
    "ishowspeed": ["#speed", "#speedlive", "#speedclips", "#speedrage"],
    "botez": ["#botez", "#botezlive", "#botezsisters", "#alexandrabotez", "#andreabotez"],
    "xqc": ["#xqc", "#xqcow", "#xqcclips", "#xqcreacts", "#xqcdrama", "#juicer"],
    "asmongold": ["#asmongold", "#zackrawrr", "#asmon", "#asmonreacts", "#asmongoldclips"],
    "adin": ["#adinross", "#adin", "#adinlive", "#adinclips"],
    "kai": ["#kaicenat", "#kai", "#kaiclips", "#mafiathon", "#amp", "#kaicenatrage"]
}

STREAMER_PROFILES = {
    "asmong": {
        "display_name": "Asmongold (Zackrawrr)",
        "handle": "@zackrawrr",
        "youtube": "@AsmongoldTV",
        "url": "https://www.twitch.tv/zackrawrr"
    },
    "asmongold": {
        "display_name": "Asmongold (Zackrawrr)",
        "handle": "@zackrawrr",
        "youtube": "@AsmongoldTV",
        "url": "https://www.twitch.tv/zackrawrr"
    },
    "kai": {
        "display_name": "Kai Cenat",
        "handle": "@KaiCenat",
        "youtube": "@KaiCenat",
        "url": "https://www.youtube.com/@KaiCenatLive"
    },
    "kaicenat": {
        "display_name": "Kai Cenat",
        "handle": "@KaiCenat",
        "youtube": "@KaiCenat",
        "url": "https://www.youtube.com/@KaiCenatLive"
    },
    "xqc": {
        "display_name": "xQc",
        "handle": "@xQc",
        "youtube": "@xQcOW",
        "url": "https://kick.com/xqc"
    },
    "botez": {
        "display_name": "BotezLive (Alexandra & Andrea)",
        "handle": "@BotezLive",
        "youtube": "@BotezLive",
        "url": "https://www.twitch.tv/botezlive"
    },
    "adin": {
        "display_name": "Adin Ross",
        "handle": "@adinross",
        "youtube": "@AdinLive",
        "url": "https://kick.com/adinross"
    },
    "adinross": {
        "display_name": "Adin Ross",
        "handle": "@adinross",
        "youtube": "@AdinLive",
        "url": "https://kick.com/adinross"
    },
    "ishowspeed": {
        "display_name": "IShowSpeed",
        "handle": "@IShowSpeed",
        "youtube": "@IShowSpeed",
        "url": "https://www.youtube.com/@IShowSpeed"
    },
    "speed": {
        "display_name": "IShowSpeed",
        "handle": "@IShowSpeed",
        "youtube": "@IShowSpeed",
        "url": "https://www.youtube.com/@IShowSpeed"
    }
}

DEFAULT_TAKEDOWN_EMAIL = os.getenv("TAKEDOWN_EMAIL", "luv5668tyagi@gmail.com")

GLOBAL_CORE_TAGS = ["#shorts", "#twitch", "#kick", "#streamer", "#funny", "#viral", "#clips", "#trending", "#fyp"]

def get_streamer_profile(
    streamer_name: str,
    channel_handle: Optional[str] = None,
    channel_url: Optional[str] = None
) -> Dict[str, str]:
    """Resolves rich profile info (display name, @handle, stream url) for attribution."""
    clean = re.sub(r"[^a-zA-Z0-9]", "", streamer_name).lower() if streamer_name else ""
    for key, prof in STREAMER_PROFILES.items():
        if key in clean or clean in key:
            return prof
    handle = channel_handle or (f"@{clean}" if clean else "@streamer")
    if not handle.startswith("@"):
        handle = f"@{handle}"
    url = channel_url or f"https://www.twitch.tv/{clean}"
    return {
        "display_name": streamer_name.title() if streamer_name else "Streamer",
        "handle": handle,
        "youtube": handle,
        "url": url
    }

def build_viral_youtube_description(
    title: str,
    streamer_name: str,
    hook_text: str = "",
    reasoning: str = "",
    channel_handle: Optional[str] = None,
    channel_url: Optional[str] = None,
    takedown_email: Optional[str] = None,
    custom_tags: Optional[List[str]] = None
) -> str:
    """
    Constructs a high-converting, viral YouTube description:
    1. Click-compelling hook & curiosity teaser.
    2. Direct streamer attribution and tagging (@handle & channel link).
    3. Engagement call-to-action (likes, comments, subscribes).
    4. Section 107 of the Copyright Act 1976 Fair Use Legal Disclaimer.
    5. Content owner takedown & direct removal email contact.
    6. Viral algorithm hashtags.
    """
    prof = get_streamer_profile(streamer_name, channel_handle, channel_url)
    tags = custom_tags or get_streamer_tags(streamer_name)
    tags_str = " ".join(tags)
    email = takedown_email or DEFAULT_TAKEDOWN_EMAIL

    teaser = ""
    if reasoning and len(reasoning) > 15:
        clean_r = reasoning.replace("\n", " ").strip()
        if not clean_r.endswith("."):
            clean_r += "."
        teaser = f"🔥 {clean_r}\n"
    elif hook_text:
        teaser = f"🔥 \"{hook_text}\"\n"

    clean_name = re.sub(r"[^a-zA-Z0-9]", "", prof.get("display_name", streamer_name)).lower()
    streamer_tag = f"#{clean_name}" if clean_name else "#streamer"
    hashtags = f"#shorts {streamer_tag} #gaming #viral #trending #fyp"

    desc = f"""{title}

{teaser}
🎮 Featured Streamer: {prof['display_name']} ({prof['handle']})
📺 Watch original stream: {prof['url']}
⚡ Clipped live with SupoClip

---
⚖️ Fair Use & Credit: Copyright Disclaimer Under Section 107 of the Copyright Act 1976. For removal: {email}

{hashtags}"""
    return desc.strip()

def get_streamer_tags(streamer_name: str) -> List[str]:
    """
    Returns empty list to guarantee clean, tag-free uploads and prevent YouTube spam soft-bans.
    """
    return []

def strip_and_embed_video_metadata(
    video_path: Path,
    title: str,
    streamer_name: str,
    custom_tags: Optional[List[str]] = None,
    description: Optional[str] = None
) -> bool:
    """
    1. Removes all previous encoder metadata (-map_metadata -1).
    2. Keeps file headers 100% clean with zero spam tag injections.
    Replaces video_path in-place atomically.
    """
    if not video_path.exists():
        logger.warning("strip_and_embed_video_metadata: Video file not found: %s", video_path)
        return False

    temp_out = video_path.with_name(f"meta_clean_{video_path.name}")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-map_metadata", "-1",
        "-c", "copy",
        "-metadata", f"title={title}",
        "-metadata", f"artist={streamer_name}",
        "-metadata:s:v:0", "handler_name=SupoClip Engine",
        str(temp_out)
    ]
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if temp_out.exists() and temp_out.stat().st_size > 1000:
            shutil.move(str(temp_out), str(video_path))
            logger.info("Successfully stripped and embedded metadata for %s into %s", streamer_name, video_path.name)
            return True
        else:
            logger.warning("Metadata embed output was empty: %s", temp_out)
            if temp_out.exists():
                temp_out.unlink(missing_ok=True)
            return False
    except Exception as e:
        logger.error("Failed to embed metadata into %s: %s", video_path, e)
        if temp_out.exists():
            temp_out.unlink(missing_ok=True)
        return False
