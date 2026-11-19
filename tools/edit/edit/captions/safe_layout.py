"""Subtitle safe area placement ensuring avoidance of TikTok / IG UI occlusion."""

from __future__ import annotations

from typing import Tuple

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

OCCLUSION_TOP = 160
OCCLUSION_BOTTOM = 420
OCCLUSION_RIGHT = 140
LEFT_MARGIN = 40

SAFE_Y_MIN = OCCLUSION_TOP
SAFE_Y_MAX = CANVAS_HEIGHT - OCCLUSION_BOTTOM  # 1500
SAFE_X_MIN = LEFT_MARGIN
SAFE_X_MAX = CANVAS_WIDTH - OCCLUSION_RIGHT    # 940


def compute_safe_caption_position(
    requested_y_ratio: float,
    text_width: int,
    text_height: int,
    canvas_w: int = CANVAS_WIDTH,
    canvas_h: int = CANVAS_HEIGHT,
) -> Tuple[int, int]:
    """Calculate (x, y) top-left anchor for subtitle, strictly clamped inside safe zone."""
    # Desired vertical center
    desired_center_y = int(requested_y_ratio * canvas_h)

    half_h = text_height // 2
    # Safe vertical bounds
    min_center_y = SAFE_Y_MIN + half_h + 10
    max_center_y = SAFE_Y_MAX - half_h - 10

    center_y = max(min_center_y, min(max_center_y, desired_center_y))
    y = max(SAFE_Y_MIN, center_y - half_h)

    # Horizontal centering within safe horizontal zone [SAFE_X_MIN, SAFE_X_MAX]
    safe_zone_center_x = (SAFE_X_MIN + SAFE_X_MAX) // 2
    x = safe_zone_center_x - (text_width // 2)

    # Clamp within horizontal margins
    x = max(SAFE_X_MIN, min(SAFE_X_MAX - text_width, x))

    return x, y
