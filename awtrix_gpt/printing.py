"""Helpers for the thermal printer: text wrapping, French timestamps, captioned photos."""

import io
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

FRENCH_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
FRENCH_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                 "août", "septembre", "octobre", "novembre", "décembre")


def wrap_text(text: str, max_width: int = 32) -> list[str]:
    """Greedy word wrap, paragraph by paragraph; words longer than the width stand alone."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current: list[str] = []
        length = 0
        for word in paragraph.split():
            if current and length + len(word) + len(current) > max_width:
                lines.append(" ".join(current))
                current, length = [], 0
            current.append(word)
            length += len(word)
        if current:
            lines.append(" ".join(current))
    return lines


def wrap_and_reverse_text(text: str, max_width: int = 32) -> str:
    """Wrap, then reverse line order: the printer prints upside down."""
    return "\n".join(reversed(wrap_text(text, max_width)))


def format_french_timestamp(now: Optional[datetime] = None) -> str:
    """'vendredi 10 octobre 2026 à 14:05', independent of the system locale."""
    now = now or datetime.now()
    return (f"{FRENCH_DAYS[now.weekday()]} {now.day:02d} {FRENCH_MONTHS[now.month - 1]} "
            f"{now.year} à {now:%H:%M}")


def add_text_to_image(image_bytes: bytes, caption: str) -> bytes:
    """Rotate the photo 180 degrees and append the caption below it, centred, as JPEG bytes."""
    image = Image.open(io.BytesIO(image_bytes)).rotate(180)

    margin, font_size, line_spacing = 40, 36, 10
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    lines = caption.split("\n")
    text_height = len(lines) * (font_size + line_spacing)
    canvas = Image.new("RGB", (image.width, image.height + text_height + 2 * margin), "white")
    canvas.paste(image, (0, 0))

    draw = ImageDraw.Draw(canvas)
    y = image.height + margin
    for line in lines:
        x = (image.width - draw.textlength(line, font=font)) // 2
        draw.text((x + 2, y + 2), line, fill="gray", font=font)
        draw.text((x, y), line, fill="black", font=font)
        y += font_size + line_spacing

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=95)
    return out.getvalue()
