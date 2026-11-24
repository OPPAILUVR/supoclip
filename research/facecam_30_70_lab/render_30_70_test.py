import sys
import subprocess
from pathlib import Path

# Target parameters (Exact 30/70 vertical 9:16 layout)
OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/sample_asmon_raw.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/test_30_70_center_render.mp4"

# 1. SCREEN / GAMEPLAY CROP: Dead Center of the stream
# 1920x1080 input. Center is at x = 960.
# For 1080x1344 output (aspect 0.80357):
# Height = 1080
# Width = 1080 * 1080 / 1344 = 868 px
# game_x = (1920 - 868) / 2 = 526 px
# This spans x = 526 to 1394, perfectly centered on the primary content!
game_w = 868
game_h = 1080
game_x = (1920 - game_w) // 2  # 526
game_y = 0

# 2. FACECAM CROP: Streamer facecam in bottom-left
# Asmon webcam at x=0:536, y=514:1080 (w=536, h=566)
# Target aspect: 1080/576 = 1.875
cam_w = 536
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 286 px
cam_x = 0
cam_y = max(514, min(1080 - cam_h, int(794 - cam_h * 0.45)))

# 3. FFmpeg Filtergraph
# - [top]: Dead center screen crop scaled to 1080x1344
# - [bottom]: Streamer facecam scaled to 1080x576
# - vstack: Stack [top] and [bottom]
# - divider: Crisp clean 3px divider at y=1342:1346
vf = (
    f"[0:v]split=2[camsrc][gamesrc];"
    f"[gamesrc]crop={game_w}:{game_h}:{game_x}:{game_y},"
    f"scale={OUT_W}:{CONTENT_H}:flags=lanczos,setsar=1[top];"
    f"[camsrc]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
    f"scale={OUT_W}:{FACECAM_H}:flags=lanczos,setsar=1[bottom];"
    f"[top][bottom]vstack=inputs=2[stacked];"
    f"[stacked]drawbox=x=0:y={CONTENT_H-2}:w={OUT_W}:h=4:color=white@0.6:t=fill[vout]"
)

cmd = [
    "ffmpeg", "-y",
    "-ss", "2", "-t", "12",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print(f"Rendering 30/70 center-cropped test video (game_x={game_x}, game_w={game_w})...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
