"""Tests for visual stability, brightness, and color temperature jumps."""

import numpy as np
from qc.stability import (
    check_visual_stability,
    compute_brightness,
    compute_color_temp_rb_ratio,
)


def test_compute_brightness_and_color_temp():
    # Pure red frame (BGR: 0, 0, 255)
    red_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    red_frame[:, :, 2] = 255
    b = compute_brightness(red_frame)
    assert b > 50  # ~0.299 * 255 = 76.2
    c = compute_color_temp_rb_ratio(red_frame)
    assert c > 100.0  # red high, blue near 0

    # Neutral gray frame
    gray_frame = np.full((100, 100, 3), 128, dtype=np.uint8)
    b_gray = compute_brightness(gray_frame)
    assert 127.0 <= b_gray <= 129.0
    c_gray = compute_color_temp_rb_ratio(gray_frame)
    assert 0.99 <= c_gray <= 1.01


def test_intra_shot_light_jump_detected():
    f1 = np.full((100, 100, 3), 50, dtype=np.uint8)
    f2 = np.full((100, 100, 3), 150, dtype=np.uint8)  # sudden 100 luma jump
    frames = [f1, f2]

    # When allow_light_change=False, must report fail
    fails, warnings, metrics = check_visual_stability(frames, allow_light_change=False)
    assert len(fails) > 0
    assert any("intra_shot_brightness_jump" in f["check"] for f in fails)
    assert metrics["max_brightness_jump"] > 50.0

    # When allow_light_change=True, only warning, no fail
    fails_allowed, warnings_allowed, _ = check_visual_stability(frames, allow_light_change=True)
    assert len(fails_allowed) == 0
    assert len(warnings_allowed) > 0


def test_cross_shot_lighting_jump():
    f_prev = np.full((100, 100, 3), 30, dtype=np.uint8)
    f_curr = np.full((100, 100, 3), 180, dtype=np.uint8)  # jump from 30 to 180 across cut
    fails, warnings, metrics = check_visual_stability([f_curr], prev_last_frame=f_prev)
    assert metrics["cross_shot_jump"] is not None
    assert metrics["cross_shot_jump"]["brightness_diff"] > 100
    assert any("cross_shot_lighting" in w["check"] for w in warnings)
