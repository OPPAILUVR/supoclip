"""YouTube Cookie Synchronization & Live Stream Probing via yt-dlp."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from ...youtube_utils import get_youtube_video_id

logger = logging.getLogger(__name__)


def normalize_streamer_url(platform: str, identifier: str) -> tuple[str, str]:
    """Normalize user input to (channel_url, channel_handle)."""
    platform = platform.lower().strip()
    identifier = identifier.strip()

    # Automatic detection of platform from identifier if specified as generic or mismatched
    if "youtube.com" in identifier.lower() or "youtu.be" in identifier.lower():
        platform = "youtube"
    elif "twitch.tv" in identifier.lower():
        platform = "twitch"
    elif "kick.com" in identifier.lower():
        platform = "kick"

    if platform == "youtube":
        clean_id = identifier.strip()
        # Direct video link (e.g. https://www.youtube.com/watch?v=4JOjgLLAr1o)
        if "watch?v=" in clean_id or "youtu.be/" in clean_id:
            vid = get_youtube_video_id(clean_id)
            if vid:
                return f"https://www.youtube.com/watch?v={vid}", f"video_{vid}"

        # Match @handle or youtube.com/@handle or channel/UC... or full live link
        if "youtube.com" in clean_id or "youtu.be" in clean_id:
            handle_match = re.search(r"@([a-zA-Z0-9_.-]+)", clean_id)
            if handle_match:
                handle = f"@{handle_match.group(1)}"
                url = f"https://www.youtube.com/{handle}/live"
            elif "/channel/" in clean_id:
                chan_match = re.search(r"/channel/([a-zA-Z0-9_.-]+)", clean_id)
                handle = chan_match.group(1) if chan_match else "channel"
                url = f"https://www.youtube.com/channel/{handle}/live"
            else:
                handle = clean_id
                url = clean_id if "/live" in clean_id else f"{clean_id.rstrip('/')}/live"
        else:
            handle = clean_id if clean_id.startswith("@") else f"@{clean_id}"
            url = f"https://www.youtube.com/{handle}/live"
        return url, handle

    elif platform == "twitch":
        clean = (
            identifier.replace("https://", "")
            .replace("http://", "")
            .replace("www.twitch.tv/", "")
            .replace("twitch.tv/", "")
            .strip("/")
        )
        handle = clean.split("/")[0]
        url = f"https://www.twitch.tv/{handle}"
        return url, handle

    elif platform == "kick":
        clean = (
            identifier.replace("https://", "")
            .replace("http://", "")
            .replace("www.kick.com/", "")
            .replace("kick.com/", "")
            .strip("/")
        )
        handle = clean.split("/")[0]
        url = f"https://kick.com/{handle}"
        return url, handle

    raise ValueError(f"Unsupported platform: {platform}. Supported: youtube, twitch, kick")


def get_youtube_cookies_file() -> Optional[str]:
    """Ensure Netscape-format cookies file exists and return its path for yt-dlp."""
    possible_dirs = [
        Path(__file__).resolve().parent.parent.parent.parent / "browser_data",
        Path("browser_data"),
        Path("backend/browser_data"),
    ]

    for bdir in possible_dirs:
        if not bdir.exists():
            continue
        json_file = bdir / "youtube_cookies.json"
        txt_file = bdir / "youtube_cookies.txt"

        # Sync JSON cookies to Netscape cookies.txt if JSON is newer or txt doesn't exist/empty
        if json_file.exists():
            try:
                needs_sync = (
                    not txt_file.exists()
                    or txt_file.stat().st_size == 0
                    or json_file.stat().st_mtime > txt_file.stat().st_mtime
                )
                if needs_sync:
                    with open(json_file, "r", encoding="utf-8") as f:
                        cookies_data = json.load(f)
                    if isinstance(cookies_data, list) and cookies_data:
                        lines = ["# Netscape HTTP Cookie File\n"]
                        for c in cookies_data:
                            domain = c.get("domain", "")
                            flag = "TRUE" if domain.startswith(".") else "FALSE"
                            path = c.get("path", "/")
                            secure = "TRUE" if c.get("secure", False) else "FALSE"
                            exp_val = c.get("expires", 0)
                            if exp_val is None or exp_val <= 0:
                                expires = "2147483647"
                            else:
                                expires = str(int(exp_val))
                            name = c.get("name", "")
                            value = c.get("value", "")
                            lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                        with open(txt_file, "w", encoding="utf-8") as f:
                            f.writelines(lines)
                        logger.info("Synchronized %d YouTube cookies to Netscape format at %s", len(cookies_data), txt_file)
            except Exception as sync_err:
                logger.warning("Failed to synchronize youtube_cookies.json to .txt: %s", sync_err)

        if txt_file.exists() and txt_file.stat().st_size > 0:
            return str(txt_file.resolve())

    return None


def probe_live_status(platform: str, channel_url: str) -> Dict[str, Any]:
    """Probe if a streamer is currently live using yt-dlp (with YouTube cookies & dual-track extraction)."""
    clean_url = channel_url.strip()
    if "youtube.com" in clean_url or "youtu.be" in clean_url:
        if "watch?v=" in clean_url and clean_url.endswith("/live"):
            clean_url = clean_url.removesuffix("/live")

    cookie_file = get_youtube_cookies_file()

    ydl_opts: Dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "playlist_items": "1",
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            if not info:
                return {"is_live": False}

            is_live = info.get("is_live") is True or info.get("live_status") == "is_live"
            if is_live:
                formats = info.get("formats") or []
                stream_url = None
                audio_url = None

                is_youtube = (
                    str(platform).lower() == "youtube"
                    or "youtube.com" in clean_url.lower()
                    or "youtu.be" in clean_url.lower()
                )

                if is_youtube and formats:
                    for f in reversed(formats):
                        f_url = f.get("url") or ""
                        vc = f.get("vcodec") or "none"
                        ac = f.get("acodec") or "none"
                        proto = f.get("protocol") or ""
                        res = str(f.get("resolution") or "")
                        is_m3u8 = "m3u8" in proto or ".m3u8" in f_url or f.get("ext") == "mp4"

                        # Video track: contains video codec
                        if is_m3u8 and vc != "none" and not stream_url:
                            stream_url = f_url
                            logger.info("YouTube Live probe: selected video format %s (%s, vc=%s, ac=%s)", f.get("format_id"), res, vc, ac)

                        # Audio track: audio-only manifest when split from video
                        if (vc == "none" or "audio" in res.lower() or (ac != "none" and vc == "none")) and not audio_url:
                            if f_url and ("m3u8" in proto or ".m3u8" in f_url or "http" in f_url):
                                audio_url = f_url
                                logger.info("YouTube Live probe: selected audio format %s (%s)", f.get("format_id"), res)

                    if not stream_url:
                        stream_url = info.get("url")
                else:
                    # Twitch / Kick or combined streams
                    stream_url = info.get("url")
                    if not stream_url and formats:
                        for f in reversed(formats):
                            if f.get("protocol", "").startswith("m3u8") or ".m3u8" in f.get("url", ""):
                                stream_url = f.get("url")
                                break

                return {
                    "is_live": True,
                    "title": info.get("title") or "Live Stream",
                    "stream_id": str(info.get("id") or ""),
                    "stream_url": stream_url or clean_url,
                    "audio_url": audio_url,
                    "is_youtube": is_youtube,
                    "thumbnail": info.get("thumbnail"),
                }
            return {"is_live": False}
    except Exception as exc:
        err_str = str(exc).lower()
        if "not currently live" in err_str or "offline" in err_str or "no video" in err_str:
            return {"is_live": False}
        logger.debug("yt-dlp live probe failed for %s (%s): %s", clean_url, platform, exc)
        return {"is_live": False, "error": str(exc)}
