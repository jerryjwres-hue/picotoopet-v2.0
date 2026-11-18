"""Captions and subtitle layout package."""

from edit.captions.bounce import calculate_bounce_scale, render_caption_on_frame
from edit.captions.safe_layout import compute_safe_caption_position

__all__ = [
    "calculate_bounce_scale",
    "render_caption_on_frame",
    "compute_safe_caption_position",
]
