import json
import numpy as np
from collections import Counter

file_path = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/gta_study/gta5_frame_analysis_1000.jsonl"

records = []
with open(file_path, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

print(f"Loaded {len(records)} records from {file_path}")

durations = []
shock_scores = []
laughter_scores = []
face_ratios = []
quadrants = Counter()
peak_motion_rel_positions = []
mean_motions = []
wpm_list = []
word_counts = []
title_lens = []
view_counts = []
categories = Counter()
channels = Counter()

success_count = 0
for r in records:
    if r.get("status") != "success":
        continue
    success_count += 1
    
    fa = r.get("frame_analysis", {})
    dur = fa.get("duration_s", 0)
    if dur > 0:
        durations.append(dur)
    
    vc = r.get("views", 0)
    view_counts.append(vc if vc else 0)

    category = r.get("category", "unknown")
    categories[category] += 1
    
    channel = r.get("channel", "unknown")
    channels[channel] += 1

    # facecam
    facecam = fa.get("facecam", {})
    face_ratio = facecam.get("presence_ratio", 0)
    face_ratios.append(face_ratio)
    quad = facecam.get("dominant_quadrant", "none")
    quadrants[quad] += 1
    
    # emotions
    emo = fa.get("emotions", {})
    shock_scores.append(emo.get("shock_ratio", 0))
    laughter_scores.append(emo.get("laughter_ratio", 0))
    
    # motion
    motion = fa.get("gameplay_dynamics", {})
    mean_motions.append(motion.get("avg_motion_energy", 0))
    peak_sec = motion.get("peak_motion_sec", 0)
    if dur > 0:
        peak_motion_rel_positions.append(peak_sec / dur)
        
    # speech / whisper
    trans = r.get("transcript", {})
    text = trans.get("text", "")
    words = text.split()
    wc = len(words)
    word_counts.append(wc)
    wps = wc / dur if dur > 0 else 0
    wpm_list.append(wps * 60)
    
    # title
    title = r.get("title", "")
    title_lens.append(len(title))

print(f"Successfully processed records: {success_count}/{len(records)}")
print("\n=== COMPLETE 1,000 GTA 5 SHORTS EMPIRICAL ANALYSIS ===")
print(f"Total Analyzed: {len(durations)} videos")
print(f"Views: Mean={np.mean(view_counts):,.0f}, Median={np.median(view_counts):,.0f}, Max={np.max(view_counts):,.0f}, Total={np.sum(view_counts):,.0f}")
print(f"Duration: Mean={np.mean(durations):.1f}s, Median={np.median(durations):.1f}s, Min={np.min(durations):.1f}s, Max={np.max(durations):.1f}s")
print(f"Duration Quartiles: 25%={np.percentile(durations, 25):.1f}s, 50%={np.percentile(durations, 50):.1f}s, 75%={np.percentile(durations, 75):.1f}s")

# Duration brackets
dur_brackets = {
    "< 20s": sum(1 for d in durations if d < 20),
    "20s - 35s": sum(1 for d in durations if 20 <= d <= 35),
    "35s - 50s": sum(1 for d in durations if 35 < d <= 50),
    "> 50s": sum(1 for d in durations if d > 50)
}
print(f"Duration Distribution: {dur_brackets}")

print(f"\nFacecam Presence (>10% of frames): {sum(1 for f in face_ratios if f > 0.1)} / {len(durations)} ({sum(1 for f in face_ratios if f > 0.1)/len(durations):.1%})")
print(f"Facecam Placement Breakdown: {dict(quadrants)}")

print(f"\nEmotions:")
print(f"  Shock Ratio: Mean={np.mean(shock_scores):.4f}, Peak Max={np.max(shock_scores):.4f}, Clips with Shock: {sum(1 for s in shock_scores if s > 0)} ({sum(1 for s in shock_scores if s > 0)/len(durations):.1%})")
print(f"  Laughter Ratio: Mean={np.mean(laughter_scores):.4f}, Peak Max={np.max(laughter_scores):.4f}, Clips with Laughter: {sum(1 for l in laughter_scores if l > 0)} ({sum(1 for l in laughter_scores if l > 0)/len(durations):.1%})")
print(f"  Shock vs Laughter Ratio: Mean Shock is {(np.mean(shock_scores)/(np.mean(laughter_scores) if np.mean(laughter_scores)>0 else 1)):.2f}x higher than Laughter!")

print(f"\nMotion & Climax Dynamics:")
print(f"  Mean Motion Energy: {np.mean(mean_motions):.2f}")
print(f"  Peak Climax Relative Position: Mean={np.mean(peak_motion_rel_positions):.1%}, Median={np.median(peak_motion_rel_positions):.1%}")

print(f"\nSpeech & Audio (Whisper):")
print(f"  Words Per Minute: Mean={np.mean(wpm_list):.1f} WPM, Median={np.median(wpm_list):.1f} WPM")
print(f"  Total Words per Clip: Mean={np.mean(word_counts):.1f} words, Median={np.median(word_counts):.1f} words")

print(f"\nTitles & Hooks:")
print(f"  Title Character Length: Mean={np.mean(title_lens):.1f} chars, Median={np.median(title_lens):.1f} chars")

# Correlation with Top 10% vs Bottom 10%
indexed_views = sorted(enumerate(view_counts), key=lambda x: x[1], reverse=True)
top_100_idx = [x[0] for x in indexed_views[:100]]
bot_100_idx = [x[0] for x in indexed_views[-100:]]

def subset_stats(indices, label):
    sub_dur = [durations[i] for i in indices]
    sub_shock = [shock_scores[i] for i in indices]
    sub_laugh = [laughter_scores[i] for i in indices]
    sub_face = [face_ratios[i] for i in indices]
    sub_climax = [peak_motion_rel_positions[i] for i in indices]
    sub_wpm = [wpm_list[i] for i in indices]
    sub_views = [view_counts[i] for i in indices]
    print(f"\n[{label}] (N={len(indices)}):")
    print(f"  Avg Views: {np.mean(sub_views):,.0f} (Median: {np.median(sub_views):,.0f})")
    print(f"  Duration: {np.mean(sub_dur):.1f}s (Median: {np.median(sub_dur):.1f}s)")
    print(f"  Shock Score: {np.mean(sub_shock):.4f} (Clips w/ Shock: {sum(1 for s in sub_shock if s > 0)}/{len(indices)})")
    print(f"  Laughter Score: {np.mean(sub_laugh):.4f} (Clips w/ Laughter: {sum(1 for l in sub_laugh if l > 0)}/{len(indices)})")
    print(f"  Facecam Presence: {np.mean(sub_face):.1%}")
    print(f"  Climax Position: {np.mean(sub_climax):.1%}")
    print(f"  Speech WPM: {np.mean(sub_wpm):.1f} WPM")

subset_stats(top_100_idx, "TOP 10% (HIGHEST VIEWS)")
subset_stats(bot_100_idx, "BOTTOM 10% (LOWEST VIEWS)")

