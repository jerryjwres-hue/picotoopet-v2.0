"""Animated subtitle renderer featuring bounce-in effect and thick black outline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from edit.captions.safe_layout import compute_safe_caption_position


def calculate_bounce_scale(time_since_start: float, bounce_dur: float = 0.25) -> float:
    """Calculate scale multiplier using back-out elastic spring overshoot."""
    if time_since_start >= bounce_dur:
        return 1.0
    if time_since_start <= 0.0:
        return 0.0

    p = time_since_start / float(bounce_dur)
    # Standard back-out overshoot easing: s = 1.70158
    s = 1.70158
    p1 = p - 1.0
    scale = 1.0 + (s + 1.0) * (p1 ** 3) + s * (p1 ** 2)
    return float(np.clip(scale, 0.0, 1.25))


def render_caption_on_frame(
    frame_bgr: np.ndarray,
    text: str,
    time_since_start: float,
    y_ratio: float = 0.20,
    font_path: Optional[str] = None,
    base_font_size: int = 56,
    stroke_width: int = 6,
) -> np.ndarray:
    """Draw white text with black outline and dynamic bounce-in animation onto frame."""
    if not text:
        return frame_bgr

    h, w = frame_bgr.shape[:2]
    scale = calculate_bounce_scale(time_since_start, bounce_dur=0.25)
    if scale < 0.05:
        # Before appearance
        return frame_bgr

    font_size = max(16, int(round(base_font_size * scale)))

    # Load font with fallback
    font = None
    if font_path and Path(font_path).is_file():
        try:
            font = ImageFont.truetype(str(font_path), size=font_size)
        except Exception:
            font = None
    if font is None:
        try:
            font = ImageFont.truetype("arial.ttf", size=font_size)
        except Exception:
            font = ImageFont.load_default()

    img_rgb = Image.fromarray(frame_bgr[:, :, ::-1])
    draw = ImageDraw.Draw(img_rgb)

    scaled_stroke = max(2, int(stroke_width * scale))
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=scaled_stroke)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x, y = compute_safe_caption_position(
        requested_y_ratio=y_ratio,
        text_width=text_w,
        text_height=text_h,
        canvas_w=w,
        canvas_h=h,
    )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=(255, 255, 255),
        stroke_width=scaled_stroke,
        stroke_fill=(0, 0, 0),
    )

    return np.array(img_rgb)[:, :, ::-1]
