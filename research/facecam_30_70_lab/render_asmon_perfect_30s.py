import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backups/backup_before_viral_engine_20261115_003920/backend/uploads/live_buffers/004732aa-748c-47fc-a78b-8c8b0e78368e/chunk_0027.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/asmon_30_70_perfect_final.mp4"

# 1. Screen / Content (10% squeezed dead-center crop)
game_w = 964
game_h = 1080
game_x = (1920 - game_w) // 2  # 478
game_y = 0
clip_h = 1210

# 2. Dynamic Facecam (Analyzed exactly from Asmon face coordinates)
# Face center: fcx = 341.7, fcy = 805.2, med_w = 139.3, med_h = 188.5
# Facecam box width: 536 px (prevents any Twitter leak)
cam_w = 536
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 286 px
cam_x = 0
# Centered on face with 45px headroom and 50px chinroom
cam_y = 664

print(f"Content: x={game_x}, y={game_y}, w={game_w}, h={game_h} -> scaled to {OUT_W}x{clip_h} padded to {OUT_W}x{CONTENT_H}")
print(f"Facecam: x={cam_x}, y={cam_y}, w={cam_w}, h={cam_h} -> scaled to {OUT_W}x{FACECAM_H}")

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
    "-ss", "5", "-t", "30",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering Asmon 30/70 perfect final video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
