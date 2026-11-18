"""Tests for speed curve interpolation and punch-in zoom effects."""

import numpy as np
from edit.fx.punch_in import apply_punch_in_zoom, compute_punch_in_scale
from edit.fx.speed_curve import SpeedCurveInterpolator
from edit.plan import PunchInSpec, SpeedKeypoint


def test_speed_curve_mapping():
    # 2.0x speed for first 1s, then 0.5x speed
    kps = [
        SpeedKeypoint(t=0.0, x=2.0),
        SpeedKeypoint(t=1.0, x=0.5),
    ]
    interp = SpeedCurveInterpolator(kps)

    # Initial speed is 2.0
    assert abs(interp.get_instantaneous_speed(0.0) - 2.0) < 1e-3

    # At t=0.5s, integral of speed is approx ~0.875
    src_t = interp.map_timeline_to_source_time(0.5)
    assert 0.5 < src_t < 1.0


def test_punch_in_easing():
    spec = PunchInSpec(t=1.0, scale=1.20, dur=0.4)

    # Before punch-in
    assert compute_punch_in_scale(0.5, spec) == 1.0

    # During easing punch-in
    mid_scale = compute_punch_in_scale(1.2, spec)
    assert 1.0 < mid_scale < 1.20

    # After punch-in
    final_scale = compute_punch_in_scale(1.5, spec)
    assert abs(final_scale - 1.20) < 1e-4


def test_punch_in_zoom_frame():
    frame = np.zeros((200, 100, 3), dtype=np.uint8)
    frame[50:150, 25:75] = 255  # white center block

    zoomed = apply_punch_in_zoom(frame, scale=1.5)
    assert zoomed.shape == (200, 100, 3)
    # Center should remain white, edges expanded
    assert np.mean(zoomed) > np.mean(frame)
