import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1152  # 60% of 1920
FACECAM_H = 768   # 40% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backups/backup_before_viral_engine_20261115_003920/backend/uploads/live_buffers/004732aa-748c-47fc-a78b-8c8b0e78368e/chunk_0027.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/asmon_40_60_squeezed_30s.mp4"

# 1. Top 60% Content (1080 x 1152)
# Center crop shifted to exclude corner webcam
game_w = 1012
game_h = 1080
game_x = 510  # Clean center crop with 0 corner webcam bleed
game_y = 0

# 2. Bottom 40% Facecam (1080 x 768)
# Whole webcam height y=660:1080 (420px) squeezed 10% into 768px tile
cam_w = 536
cam_h = 420
cam_x = 0
cam_y = 660

print(f"60% Content: x={game_x}, y={game_y}, w={game_w}, h={game_h} -> scaled to {OUT_W}x{CONTENT_H}")
print(f"40% Facecam: x={cam_x}, y={cam_y}, w={cam_w}, h={cam_h} -> scaled to {OUT_W}x{FACECAM_H} (10% squeeze)")

vf = (
    f"[0:v]split=2[camsrc][gamesrc];"
    f"[gamesrc]crop={game_w}:{game_h}:{game_x}:{game_y},"
    f"scale={OUT_W}:{CONTENT_H}:flags=lanczos,setsar=1[top];"
    f"[camsrc]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
    f"scale={OUT_W}:{FACECAM_H}:flags=lanczos,setsar=1[bottom];"
    f"[top][bottom]vstack=inputs=2[stacked];"
    f"[stacked]drawbox=x=0:y={CONTENT_H-2}:w={OUT_W}:h=4:color=white@0.5:t=fill[vout]"
)

cmd = [
    "ffmpeg", "-y",
    "-ss", "5", "-t", "30",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering Asmon 40/60 video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Output saved to:", output_video)
