import subprocess
import sys

OUT_W = 1080
OUT_H = 1920
CONTENT_H = 1344  # 70% of 1920
FACECAM_H = 576   # 30% of 1920

input_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/backups/backup_before_viral_engine_20261115_003920/backend/uploads/live_buffers/004732aa-748c-47fc-a78b-8c8b0e78368e/chunk_0016.mp4"
output_video = "/Users/luv/.gemini/antigravity/scratch/supoclip/research/facecam_30_70_lab/asmon_30s_30_70.mp4"

# 1. SCREEN / GAMEPLAY: Squeezed 10% from center crop
# In 10% squeeze: clip_h = int(1344 * 0.90) = 1210 px
# Aspect ratio 1080 / 1210 -> input crop width = int(1080 * 1080 / 1210) = 964 px
# Centered at X = 960 -> game_x = (1920 - 964) / 2 = 478 px
# Padded to 1080x1344 with 67px bar on top and 67px bar between clip & facecam
game_w = 964
game_h = 1080
game_x = (1920 - game_w) // 2  # 478
game_y = 0
clip_h = 1210

# 2. FACECAM:
# Asmon webcam at x=0:536, y=514:1080 (w=536, h=566)
# Target aspect: 1080/576 = 1.875
# cam_w = 536 -> cam_h = int(536 * 576 / 1080) = 286 px
cam_w = 536
cam_h = int(cam_w * FACECAM_H / OUT_W)  # 286 px
cam_x = 0
# Center around Asmon face (cy ~ 794)
cam_y = max(514, min(1080 - cam_h, int(794 - cam_h * 0.45)))

print(f"Asmon 30s Config: Game Crop (w={game_w}, h={game_h}, x={game_x}, y={game_y}) -> scaled to {OUT_W}x{clip_h} padded to {OUT_W}x{CONTENT_H}")
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
    "-ss", "10", "-t", "30",
    "-i", input_video,
    "-filter_complex", vf,
    "-map", "[vout]",
    "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
    "-c:a", "aac", "-b:a", "192k",
    output_video
]

print("Rendering Asmongold 30-second 30/70 video...")
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("FFmpeg error:", res.stderr)
    sys.exit(1)

print("Render complete! Saved to:", output_video)
