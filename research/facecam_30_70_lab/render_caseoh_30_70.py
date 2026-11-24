import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/uploads/live_buffers/09849f5b-6b0e-40d8-bed2-dc3f7bc1cb1b/chunk_0000.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/caseoh_30_70_sample.mp4"

# 1. SCREEN / GAMEPLAY CROP: Dead Center of the stream
# 1920x1080 input. Center at x = 960.
# For 1080x1344 output: w = 868, h = 1080, x = 526, y = 0
game_w = 868
game_h = 1080
game_x = (1920 - game_w) // 2  # 526
game_y = 0

# 2. FACECAM CROP: CaseOh webcam in TOP-LEFT
# Detected webcam box: x=0:404, y=97:435 (w=404, h=338)
# Face center: y ~ 310 in full frame
# Target aspect: 1080/576 = 1.875
cam_w = 404
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 215 -> round to 216
cam_x = 0
cam_y = max(97, min(435 - cam_h, 212))

print(f"CaseOh Config: Content (w={game_w}, h={game_h}, x={game_x}, y={game_y}) | Facecam (w={cam_w}, h={cam_h}, x={cam_x}, y={cam_y})")

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
    "-ss", "10", "-t", "15",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering CaseOh 30/70 test video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
