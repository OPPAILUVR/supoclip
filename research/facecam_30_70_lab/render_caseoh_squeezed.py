import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/uploads/live_buffers/09849f5b-6b0e-40d8-bed2-dc3f7bc1cb1b/chunk_0000.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/caseoh_30_70_squeezed.mp4"

# 1. SCREEN / GAMEPLAY: Squeezed full 16:9 fit into the top 70% tile
# Input is 1920x1080. Scaled to width 1080 -> height = 608.
# In a 1080x1344 canvas, centered vertically:
# Black bar above = (1344 - 608) / 2 = 368 px
# Game clip = 1080 x 608
# Black bar between clip and facecam = 368 px
# Facecam = 1080 x 576

# 2. FACECAM:
# CaseOh webcam in TOP-LEFT: x=0:404, y=97:435 (w=404, h=338)
cam_w = 404
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 216 px
cam_x = 0
cam_y = max(97, min(435 - cam_h, 212))

# Top tile filter: scale full 16:9 game to 1080x608, then pad to 1080x1344 with black bars above and below
# Bottom tile filter: crop webcam and scale to 1080x576
vf = (
    f"[0:v]split=2[camsrc][gamesrc];"
    f"[gamesrc]scale={OUT_W}:608:flags=lanczos,pad={OUT_W}:{CONTENT_H}:(ow-iw)/2:(oh-ih)/2:color=black[top];"
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

print("Rendering CaseOh 30/70 squeezed test video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
