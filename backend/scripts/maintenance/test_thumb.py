import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from pathlib import Path

video_path = "/Users/luv/.gemini/antigravity/scratch/supoclip/backend/clips/live_cca7da2f_1794728815_57077ce1.mp4"
output_path = "/Users/luv/.gemini/antigravity/brain/f8c2c488-830f-4375-9e1e-3e37c7a0d8a2/xqc_95_viral_thumbnail.jpg"

cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration = total_frames / fps

print(f"Video duration: {duration:.2f}s, total frames: {total_frames}")

# Midpoint climax window: 38% to 55%
start_f = int(total_frames * 0.35)
end_f = int(total_frames * 0.60)

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

best_frame = None
best_score = -1
best_sec = 0

step = max(1, int(fps * 0.5)) # sample every 0.5s

for f_idx in range(start_f, end_f, step):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret:
        continue
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # sharpness
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    # faces
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
    face_score = len(faces) * 500
    if len(faces) > 0:
        # size of largest face
        w_max = max(w * h for (x, y, w, h) in faces)
        face_score += w_max
        
    score = face_score + sharpness
    if score > best_score:
        best_score = score
        best_frame = frame.copy()
        best_sec = f_idx / fps

cap.release()
print(f"Best frame picked at {best_sec:.2f}s with score {best_score}")

if best_frame is None:
    raise RuntimeError("Could not find suitable frame")

# Convert to PIL
rgb_frame = cv2.cvtColor(best_frame, cv2.COLOR_BGR2RGB)
img = Image.fromarray(rgb_frame)

# Resize/pad to vertical 1080x1920 if needed
w, h = img.size
if (w, h) != (1080, 1920):
    img = img.resize((1080, 1920), Image.Resampling.LANCZOS)

# Color Grading: Boost vibrance & saturation (+25%), contrast (+15%)
sat_enhancer = ImageEnhance.Color(img)
img = sat_enhancer.enhance(1.30)

con_enhancer = ImageEnhance.Contrast(img)
img = con_enhancer.enhance(1.15)

# High-CTR Overlay:
# Text: "HE BROKE HIS DESK?!"
draw = ImageDraw.Draw(img)

# Try Impact font
font_path = "/System/Library/Fonts/Supplemental/Impact.ttf"
font_size = 110
font = ImageFont.truetype(font_path, font_size)

text_lines = ["HE BROKE", "HIS DESK?!"]
text_color = (255, 230, 0) # Electric Yellow #FFE600
stroke_color = (0, 0, 0)
stroke_width = 10

# Position in upper-third safe zone (Y: 280-450)
cur_y = 300
for line in text_lines:
    bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (1080 - text_w) // 2
    
    # Draw drop shadow
    shadow_offset = 12
    draw.text((text_x + shadow_offset, cur_y + shadow_offset), line, font=font, fill=(0, 0, 0, 200), stroke_width=stroke_width, stroke_fill=(0, 0, 0))
    # Draw main text with heavy stroke
    draw.text((text_x, cur_y), line, font=font, fill=text_color, stroke_width=stroke_width, stroke_fill=stroke_color)
    cur_y += text_h + 30

# Add a red accent reaction pill at the bottom of the text
accent_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 46)
accent_text = "💥 INSTANT KARMA 💀"
accent_bbox = draw.textbbox((0, 0), accent_text, font=accent_font)
aw = accent_bbox[2] - accent_bbox[0]
ah = accent_bbox[3] - accent_bbox[1]
ax = (1080 - aw) // 2
ay = cur_y + 10

# Draw pill background (Red #E50914)
pad_x = 35
pad_y = 15
pill_box = [ax - pad_x, ay - pad_y, ax + aw + pad_x, ay + ah + pad_y]
draw.rounded_rectangle(pill_box, radius=25, fill=(229, 9, 20), outline=(255, 255, 255), width=4)
draw.text((ax, ay), accent_text, font=accent_font, fill=(255, 255, 255))

# Save image
img.save(output_path, "JPEG", quality=95)
print(f"Thumbnail saved successfully to {output_path}")

