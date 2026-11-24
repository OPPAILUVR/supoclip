import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/uploads/live_buffers/09849f5b-6b0e-40d8-bed2-dc3f7bc1cb1b/chunk_0000.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/caseoh_30_70_10pct_squeezed.mp4"

# 1. SCREEN / GAMEPLAY: Squeezed exactly 10% from the previous version
# In previous version: height was 1344.
# 10% squeeze -> height = int(1344 * 0.90) = 1210 px
# Padding above = (1344 - 1210) / 2 = 67 px
# Padding between clip & facecam = 67 px
# To fit width 1080 and height 1210 without distortion:
# Input crop: game_w = int(1080 * 1080 / 1210) = 964 px, game_h = 1080 px
# Centered horizontally: game_x = (1920 - 964) / 2 = 478 px
# Since 478 > 404 (CaseOh webcam width), the corner webcam is 100% EXCLUDED!
# Only ONE facecam exists: the zoomed one at the bottom!
game_w = 964
game_h = 1080
game_x = (1920 - game_w) // 2  # 478
game_y = 0

clip_h = 1210

# 2. FACECAM:
# CaseOh webcam in TOP-LEFT: x=0:404, y=97:435 (w=404, h=338)
cam_w = 404
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 216 px
cam_x = 0
cam_y = max(97, min(435 - cam_h, 212))

print(f"10% Squeeze Config: Content Crop (w={game_w}, h={game_h}, x={game_x}, y={game_y}) -> scaled to {OUT_W}x{clip_h} padded to {OUT_W}x{CONTENT_H}")
print(f"Facecam Crop (w={cam_w}, h={cam_h}, x={cam_x}, y={cam_y}) -> scaled to {OUT_W}x{FACECAM_H}")

vf = (
    f"[0:v]split=2[camsrc][gamesrc];"
    f"[gamesrc]crop={game_w}:{game_h}:{game_x}:{game_y},"
    f"scale={OUT_W}:{clip_h}:flags=lanczos,"
    f"pad={OUT_W}:{CONTENT_H}:(ow-iw)/2:(oh-ih)/2:color=black[top];"
    f"[camsrc]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
    f"scale={OUT_W}:{FACECAM_H}:flags=lanczos,setsar=1[bottom];"
    f"[top][bottom]vstack=inputs=2[stacked];"
    f"[stacked]drawbox=x=0:y={CONTENT_H-2}:w={OUT_W}:h=4:color=white@0.4:t=fill[vout]"
)

cmd = [
    "ffmpeg", "-y",
    "-ss", "10", "-t", "15",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering CaseOh 30/70 with 10% squeeze...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
