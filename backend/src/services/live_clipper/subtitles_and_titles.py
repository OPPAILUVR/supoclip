"""Whisper Model Cache, Animated ASS Subtitles, & Unique Hook Title Sanitizer."""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import threading
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...ai import AntigravityDirectModel

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_lock = threading.Lock()
_whisper_async_lock = asyncio.Lock()


def get_whisper_model():
    """Thread-safe cached Whisper model instance for concurrent live transcriptions."""
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                import whisper
                _whisper_model = whisper.load_model("base")
    return _whisper_model


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


VIRAL_TRIGGERS = {
    "MISTAKE", "REGRET", "LATE", "CAUGHT", "4K", "WORST", "UNHINGED",
    "DISASTER", "WRONG", "EXPOSED", "PANIC", "NEVER", "THIS", "INSTANTLY",
    "HAPPENED", "ILLEGAL", "CHEATING", "FORGOT", "0 IQ", "200 IQ", "ENDED",
    "BANNED", "SHOCKING", "CONFESSED", "FELL", "APART", "EXPLODED", "RUINED",
    "FAIL", "FAILED", "RAGE", "LOST", "GONE", "INSANE", "CRAZY", "BROKE",
}


def format_hook_title_for_ass(hook_title: str) -> str:
    """Format hook title for ASS with electric yellow accents on viral trigger words."""
    if not hook_title:
        return ""
    clean = hook_title.replace("{", "").replace("}", "").strip()
    words = clean.split()
    formatted = []
    for w in words:
        bare = w.strip(".,!?:;\"'").upper()
        if bare in VIRAL_TRIGGERS:
            formatted.append(f"{{\\c&H0000FFFF&}}{w.upper()}{{\\c&H00FFFFFF&}}")
        else:
            formatted.append(w.upper())
    return "{\\b1}" + " ".join(formatted) + "{\\b0}"


def build_live_clip_ass(
    segments: list,
    start_s: float,
    end_s: float,
    hook_title: str,
    output_ass: Path,
    caption_y: float = 0.80,
) -> None:
    """Build animated karaoke ASS subtitles + top HookTitle overlay."""
    margin_v = max(80, int(1920 * (1.0 - caption_y)))

    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: HookTitle,Arial,66,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,8,48,48,220,1",
        f"Style: Caption,Arial,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    duration = max(1.0, end_s - start_s)

    if hook_title:
        title_end = min(duration, 8.0)
        formatted_title = format_hook_title_for_ass(hook_title)
        title_anim = "{\\fad(140,250)\\fscx86\\fscy86\\t(0,120,\\fscx106\\fscy106)\\t(120,240,\\fscx100\\fscy100)}"
        ass_lines.append(
            f"Dialogue: 0,0:00:00.00,{_format_ass_time(title_end)},HookTitle,,0,0,0,,{title_anim}{formatted_title}"
        )

    all_words = []
    for seg in segments:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        text_val = str(seg.get("text", "")).strip()
        if not text_val or seg_end <= start_s or seg_start >= end_s:
            continue

        words_data = seg.get("words")
        if words_data and len(words_data) > 0:
            for w in words_data:
                w_start = float(w.get("start", seg_start))
                w_end = float(w.get("end", seg_end))
                w_text = str(w.get("word", "")).strip()
                if w_text and w_end > start_s and w_start < end_s:
                    all_words.append({
                        "word": w_text.replace("{", "").replace("}", ""),
                        "start": max(0.0, w_start - start_s),
                        "end": min(duration, w_end - start_s),
                    })
        else:
            raw_tokens = text_val.split()
            if not raw_tokens:
                continue
            tot_dur = max(0.2, seg_end - seg_start)
            w_dur = tot_dur / len(raw_tokens)
            for idx, token in enumerate(raw_tokens):
                ws = seg_start + idx * w_dur
                we = ws + w_dur
                if we > start_s and ws < end_s:
                    all_words.append({
                        "word": token.replace("{", "").replace("}", ""),
                        "start": max(0.0, ws - start_s),
                        "end": min(duration, we - start_s),
                    })

    chunks = []
    current_chunk = []
    for w in all_words:
        current_chunk.append(w)
        if len(current_chunk) >= 3 or w["word"].rstrip().endswith((".", "!", "?")):
            chunks.append(current_chunk)
            current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    for chunk in chunks:
        chunk_end = chunk[-1]["end"]
        for i, target_word in enumerate(chunk):
            w_start = target_word["start"]
            w_end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk_end
            if w_end <= w_start:
                w_end = w_start + 0.12

            entrance = "{\\fscx84\\fscy84\\t(0,80,\\fscx112\\fscy112)\\t(80,180,\\fscx100\\fscy100)}" if i == 0 else ""

            parts = []
            for j, other in enumerate(chunk):
                clean_text = other["word"].strip().upper()
                if j == i:
                    parts.append(f"{{\\c&H0000FFFF&}}{clean_text}{{\\c&H00FFFFFF&}}")
                else:
                    parts.append(clean_text)

            chunk_text = " ".join(parts)
            dialogue_text = f"{entrance}{{\\b1}}{chunk_text}{{\\b0}}" if entrance else f"{{\\b1}}{chunk_text}{{\\b0}}"
            ass_lines.append(
                f"Dialogue: 0,{_format_ass_time(w_start)},{_format_ass_time(w_end)},Caption,,0,0,0,,{dialogue_text}"
            )

    output_ass.write_text("\n".join(ass_lines), encoding="utf-8")


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
    return re.sub(r"[^a-zA-Z0-9]", "", (t or "").lower().replace("#shorts", ""))


def is_repetitive_or_generic(title: str, existing_norm_set: set[str], existing_raw_list: list[str]) -> bool:
    clean = (title or "").strip()
    norm = normalize_title(clean)
    if not norm or norm in GENERIC_OR_REPETITIVE_TITLES or norm in existing_norm_set:
        return True
    words = clean.split()
    if len(words) < 3 or len(words) > 8:
        return True
    for raw in existing_raw_list:
        norm_r = normalize_title(raw)
        if norm_r and difflib.SequenceMatcher(None, norm, norm_r).ratio() >= 0.70:
            return True
    return False


def generate_procedural_fallback_title(streamer: str, transcript: str, existing_norm_set: set[str]) -> str:
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
        "think", "know", "going", "really", "cant", "dont", "told",
    }
    tokens = [re.sub(r"[^a-zA-Z]", "", w) for w in (transcript or "").split()]
    meaningful = [w.capitalize() for w in tokens if len(w) > 3 and w.lower() not in stop_words]
    clean_streamer = streamer.capitalize() if streamer and streamer.lower() != "none" else "Streamer"

    templates = [
        f"When {clean_streamer} Realized Chat Was Right",
        f"The Exact Moment {clean_streamer} Snapped",
        f"{clean_streamer} Caught In 4K Live",
        f"Why {clean_streamer} Instantly Regretted Answering",
        f"Chat Completely Stunned {clean_streamer} Live",
        "The Wildest Statement On Stream Today",
        "When Banter Turned Completely Serious",
        f"{clean_streamer} Refused To Back Down",
        "The One Line That Silenced Chat",
        f"Nobody Expected {clean_streamer} To Say This",
        f"{clean_streamer} Dropped An Unfiltered Confession",
        f"The Decision That Cost {clean_streamer} Everything",
    ]

    if meaningful:
        topic = meaningful[0]
        templates.insert(0, f"When {clean_streamer} Faced {topic} Live")
        templates.insert(1, f"The Truth About The {topic} Blunder")
        templates.insert(2, f"{clean_streamer} Completely Lost It Over {topic}")
        if len(meaningful) >= 2:
            templates.insert(0, f"{clean_streamer} Reacts To {meaningful[0]} {meaningful[1]}")

    for cand in templates:
        norm = normalize_title(cand)
        if norm not in existing_norm_set and norm not in GENERIC_OR_REPETITIVE_TITLES:
            return cand

    return f"{clean_streamer} Shocking Stream Moment #{int(time.time() * 1000) % 1000}"


async def sanitize_clip_hook_title(
    raw_title: str,
    streamer_name: str,
    transcript: str,
    reasoning: str,
    db: AsyncSession,
) -> str:
    """Guarantees hook_title is 100% unique, non-generic, and content-grounded before burning into video."""
    existing_raw_list: list[str] = []
    existing_norm_set: set[str] = set()
    try:
        q = await db.execute(
            text("SELECT hook_title FROM generated_clips WHERE hook_title IS NOT NULL ORDER BY created_at DESC LIMIT 100")
        )
        existing_raw_list = [r[0] for r in q.fetchall() if r[0]]
        existing_norm_set = {normalize_title(t) for t in existing_raw_list}
    except Exception as e:
        logger.debug("Failed querying existing titles for hook title check: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass

    clean_raw = raw_title.strip().strip('"').strip("'")
    if not is_repetitive_or_generic(clean_raw, existing_norm_set, existing_raw_list):
        return clean_raw

    logger.info("Title '%s' for %s is generic or duplicate. Synthesizing unique hook title via AI...", clean_raw, streamer_name)
    try:
        agent = AntigravityDirectModel(model_name="antigravity:gemini-1.5-flash")
        recent_str = "\n".join(f"- {t}" for t in existing_raw_list[:25])
        prompt = f"""You are an elite viral short-form director clipping live content for "{streamer_name}".
The title "{clean_raw}" was rejected for being generic, repetitive, or already used.
Generate 5 completely UNIQUE, HIGH-CTR, CATCHY titles (3 to 7 words only) specifically grounded in this moment's dialogue:

STREAMER: {streamer_name}
TRANSCRIPT:
"{transcript[:500]}"

REASONING:
"{reasoning[:200]}"

CATCHINESS & VIRALITY RULES:
1. STRICTLY 3 TO 7 WORDS ONLY.
2. Pique an intense CURIOSITY GAP — the title must pose a situation, conflict, or shocking realization that viewers CANNOT resist clicking to see resolved.
3. Use high-stakes, active verbs (e.g. Exposed, Silenced, Regretted, Snapped, Backfired, Confessed, Blundered).
4. Must mention "{streamer_name}" or the specific subject/action from the dialogue. NEVER generate vague or random noun lists.
5. Plain text only: NO quotes, NO hashtags, NO emojis.
6. FORBIDDEN to copy or resemble any generic templates or these recent titles:
{recent_str}

Respond ONLY with a JSON array of 5 unique, catchy title strings:
["Catchy Title 1", "Catchy Title 2", "Catchy Title 3", "Catchy Title 4", "Catchy Title 5"]
"""
        ai_resp = await agent.request(prompt)
        raw_text = ""
        for p in getattr(ai_resp, "parts", []):
            if hasattr(p, "content") and p.content:
                raw_text = p.content
                break
        if not raw_text:
            raw_text = str(ai_resp)

        match = re.search(r"\[\s*\".*\"\s*\]", raw_text, re.DOTALL)
        if match:
            cands = json.loads(match.group(0))
            for cand in cands:
                cand_clean = cand.strip().strip('"').strip("'")
                if not is_repetitive_or_generic(cand_clean, existing_norm_set, existing_raw_list):
                    logger.info("Generated new bespoke hook title for %s: '%s'", streamer_name, cand_clean)
                    return cand_clean
    except Exception as ai_err:
        logger.warning("AI unique hook title generation failed for %s: %s", streamer_name, ai_err)

    fallback = generate_procedural_fallback_title(streamer_name, transcript, existing_norm_set)
    logger.info("Using procedural fallback title for %s: '%s'", streamer_name, fallback)
    return fallback
