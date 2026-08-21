"""Gera uma thumbnail para cada short: um frame do meio do clipe com o
titulo (gerado pelo Gemini) escrito por cima, na metade inferior da
imagem, usando a fonte Road Rage."""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

THUMBS_DIR = "thumbnails"
FONT_PATH = os.path.join("assets", "fonts", "RoadRage-Regular.ttf")
THUMB_SIZE = (1080, 1920)  # mesmo formato do short
FONT_SIZE = 130
TEXT_COLOR = (255, 255, 255)
STROKE_COLOR = (0, 0, 0)
STROKE_WIDTH = 7
TEXT_Y_RATIO = 0.62  # um pouco abaixo da metade da imagem
MAX_TEXT_WIDTH_RATIO = 0.85


def _extract_middle_frame(clip_path: str, out_jpg: str):
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            clip_path,
        ],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())
    middle = duration / 2
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(middle),
            "-i", clip_path,
            "-frames:v", "1",
            "-q:v", "2",
            out_jpg,
        ],
        check=True,
    )


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_thumbnail(clip_path: str, title: str, out_path: str) -> str:
    os.makedirs(THUMBS_DIR, exist_ok=True)
    frame_path = out_path.replace(".jpg", "_frame.jpg")
    _extract_middle_frame(clip_path, frame_path)

    img = Image.open(frame_path).convert("RGB").resize(THUMB_SIZE)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    max_width = THUMB_SIZE[0] * MAX_TEXT_WIDTH_RATIO
    lines = _wrap_text(draw, title.upper(), font, max_width)

    line_height = FONT_SIZE * 1.15
    total_height = line_height * len(lines)
    start_y = THUMB_SIZE[1] * TEXT_Y_RATIO - total_height / 2

    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        x = (THUMB_SIZE[0] - w) / 2
        y = start_y + i * line_height
        draw.text(
            (x, y), line, font=font, fill=TEXT_COLOR,
            stroke_width=STROKE_WIDTH, stroke_fill=STROKE_COLOR,
        )

    img.save(out_path, quality=92)
    os.remove(frame_path)
    return out_path
