import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1152  # 60% of 1920
FACECAM_H = 768   # 40% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/uploads/live_buffers/09849f5b-6b0e-40d8-bed2-dc3f7bc1cb1b/chunk_0060.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/caseoh_live_40_60_30s.mp4"

# 1. Top 60% Content (1080 x 1152)
# Dead center crop of GTA 6 standoff
game_w = 1012
game_h = 1080
game_x = 454  # 454 > 404 -> 100% excludes corner facecam
game_y = 0

# 2. Bottom 40% Facecam (1080 x 768)
# Whole webcam box x=0:404, y=126:436 (310px height) squeezed into 768px tile
cam_w = 404
cam_h = 310
cam_x = 0
cam_y = 126

print(f"CaseOh 60% Content: x={game_x}, y={game_y}, w={game_w}, h={game_h} -> scaled to {OUT_W}x{CONTENT_H}")
print(f"CaseOh 40% Facecam: x={cam_x}, y={cam_y}, w={cam_w}, h={cam_h} -> scaled to {OUT_W}x{FACECAM_H} (10% squeeze)")

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
    "-ss", "10", "-t", "30",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering CaseOh live 40/60 30s video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
