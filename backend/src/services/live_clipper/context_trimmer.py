"""Context-Aware Pre-Roll/Post-Roll & Sentence Boundary Trimming for Live Clips."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

DANGLING_CONNECTIVES = {
    "and", "but", "or", "nor", "because", "cause", "since", "as", "although", "though",
    "while", "whereas", "if", "unless", "until",
    "that", "which", "who", "whom", "whose", "where", "when", "why", "how", "what", "whatever", "whoever",
    "like", "with", "about", "into", "onto", "than", "to", "for", "of", "by", "in", "on", "at", "from",
    "is", "are", "was", "were", "have", "has", "had", "do", "does", "did", "would", "could", "should",
    "will", "can", "might", "must", "be", "been", "being",
    "the", "a", "an", "this", "these", "those",
    "my", "your", "his", "her", "their", "our", "its",
    "so", "then", "well", "actually", "basically", "also", "plus",
}

DANGLING_PHRASES = (
    "and let me", "let me", "let me tell", "let me explain", "the reason why",
    "the reason is", "the reason", "here is why", "here's why", "what happens is",
    "what i mean", "here it comes", "look at this", "watch this", "wait until",
    "and then", "so basically", "for example", "such as", "i mean", "you know",
    "in fact", "i think that", "i would say", "because if you", "because if",
    "and if you", "and if", "why i", "why he", "why they", "why would", "why wouldn't",
    "why would not",
)

ANTICIPATION_LEAD_IN_PHRASES = (
    "here it comes", "watch this", "look at this", "wait for it",
    "here we go", "check this out", "wait until you see",
)


def is_phrase_incomplete(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return True
    lower = raw.lower()
    if raw[-1] in (",", ";", ":", "-", "—"):
        return True
    for p in DANGLING_PHRASES:
        if lower.endswith(p) or lower.endswith(p + "."):
            return True
    for a in ANTICIPATION_LEAD_IN_PHRASES:
        if lower.endswith(a) or lower.endswith(a + "."):
            return True
    words = re.findall(r"[a-zA-Z0-9']+", lower)
    if not words:
        return True
    last_word = words[-1]
    if last_word in DANGLING_CONNECTIVES:
        if last_word == "so" and len(words) >= 2 and words[-2] in ("think", "not"):
            pass
        else:
            return True
    if raw[-1] not in (".", "!", "?"):
        return True
    return False


def apply_context_preroll_and_postroll(
    start_s: float,
    end_s: float,
    segments: List[Dict[str, Any]],
    min_duration: float = 30.0,
    max_duration: float = 175.0,
    target_sweet_spot: float = 60.0,
    source_duration: Optional[float] = None,
) -> tuple[float, float, float]:
    """Snap start/end times to natural sentence boundaries without mid-thought cuts."""
    if not segments:
        dur = min(max_duration, max(min_duration, end_s - start_s))
        if source_duration:
            dur = min(dur, max(0.1, source_duration - start_s))
        return round(start_s, 2), round(start_s + dur, 2), round(dur, 2)

    snapped_start = start_s
    best_start_idx = 0
    for idx, seg in enumerate(segments):
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        if s_start <= start_s <= s_end:
            snapped_start = s_start if (start_s - s_start) <= 1.2 else start_s
            best_start_idx = idx
            break
        elif s_start <= start_s:
            best_start_idx = idx
            snapped_start = start_s

    best_end_idx = best_start_idx
    for idx in range(best_start_idx, len(segments)):
        if float(segments[idx].get("end", 0.0)) >= end_s:
            best_end_idx = idx
            break

    curr_idx = best_end_idx
    while curr_idx < len(segments):
        seg = segments[curr_idx]
        seg_end = float(seg.get("end", 0.0))
        seg_text = seg.get("text", "")
        potential_dur = seg_end - snapped_start

        if potential_dur > max_duration:
            break

        best_end_idx = curr_idx
        if potential_dur >= min_duration and not is_phrase_incomplete(seg_text):
            if potential_dur >= target_sweet_spot:
                break
        curr_idx += 1

    end_seg = segments[best_end_idx]
    if is_phrase_incomplete(end_seg.get("text", "")):
        backtrack_idx = best_end_idx - 1
        while backtrack_idx >= best_start_idx:
            cand = segments[backtrack_idx]
            cand_dur = float(cand.get("end", 0.0)) - snapped_start
            if not is_phrase_incomplete(cand.get("text", "")) and cand_dur >= min_duration:
                best_end_idx = backtrack_idx
                break
            backtrack_idx -= 1

    snapped_end = float(segments[best_end_idx].get("end", end_s)) + 0.8
    new_dur = snapped_end - snapped_start

    if new_dur < min_duration:
        deficit = min_duration - new_dur
        expand_start = min(snapped_start, deficit)
        snapped_start -= expand_start
        deficit -= expand_start
        snapped_end += deficit
        new_dur = snapped_end - snapped_start

    if new_dur > max_duration:
        backtrack_idx = best_end_idx
        while backtrack_idx >= best_start_idx:
            cand = segments[backtrack_idx]
            cand_dur = (float(cand.get("end", 0.0)) + 0.8) - snapped_start
            if cand_dur <= max_duration and not is_phrase_incomplete(cand.get("text", "")):
                if cand_dur >= min_duration:
                    best_end_idx = backtrack_idx
                    snapped_end = float(cand.get("end", 0.0)) + 0.8
                    new_dur = snapped_end - snapped_start
                    break
            backtrack_idx -= 1
        else:
            snapped_end = snapped_start + max_duration
            new_dur = max_duration

    if source_duration and snapped_end > source_duration:
        snapped_end = source_duration
        new_dur = max(0.1, snapped_end - snapped_start)

    return round(max(0.0, snapped_start), 2), round(snapped_end, 2), round(new_dur, 2)
