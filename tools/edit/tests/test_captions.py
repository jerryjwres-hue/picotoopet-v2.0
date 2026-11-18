"""Tests for subtitle safe area positioning and bounce-in animation."""

import numpy as np
from edit.captions.bounce import calculate_bounce_scale, render_caption_on_frame
from edit.captions.safe_layout import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    OCCLUSION_BOTTOM,
    OCCLUSION_TOP,
    compute_safe_caption_position,
)


def test_bounce_scale_curve():
    # At start t=0, scale is near 0
    s_start = calculate_bounce_scale(0.0, bounce_dur=0.25)
    assert s_start < 0.2

    # Near middle (t=0.15s), scale overshoots > 1.0
    s_mid = calculate_bounce_scale(0.15, bounce_dur=0.25)
    assert s_mid >= 1.0

    # At end t >= 0.25, settles to 1.0
    s_end = calculate_bounce_scale(0.25, bounce_dur=0.25)
    assert abs(s_end - 1.0) < 1e-4


def test_safe_zone_clamping():
    # If requested in top occlusion zone (< 160)
    x, y = compute_safe_caption_position(
        requested_y_ratio=0.03,
        text_width=400,
        text_height=80,
    )
    # Must be pushed down below top occlusion zone
    assert y >= OCCLUSION_TOP

    # If requested in bottom occlusion zone (> 1500)
    x_bot, y_bot = compute_safe_caption_position(
        requested_y_ratio=0.92,
        text_width=400,
        text_height=80,
    )
    # Must be pulled up above bottom occlusion zone
    assert y_bot + 80 <= (CANVAS_HEIGHT - OCCLUSION_BOTTOM)


def test_render_caption_on_frame():
    frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    rendered = render_caption_on_frame(
        frame_bgr=frame,
        text="Maotai is ready",
        time_since_start=0.3,
        y_ratio=0.20,
    )
    assert rendered.shape == (1920, 1080, 3)
    # White text and black outline should modify frame pixels
    assert np.any(rendered > 0)
