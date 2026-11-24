import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344
FACECAM_H = 576

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backups/backup_before_viral_engine_20261115_003920/backend/uploads/live_buffers/004732aa-748c-47fc-a78b-8c8b0e78368e/chunk_0027.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/asmon_new_moment_30s.mp4"

game_w = 964
game_h = 1080
game_x = (1920 - game_w) // 2  # 478
game_y = 0
clip_h = 1210

cam_w = 536
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 286 px
cam_x = 0
cam_y = max(514, min(1080 - cam_h, 571))

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

print("Rendering Asmon new moment 30s video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
