"""Tests for Farneback optical flow motion bounds."""

import cv2
import numpy as np
from qc.motion import check_motion, compute_frame_motion


def test_static_frames_motion_underflow():
    # Two identical frames = zero flow
    f1 = np.full((480, 270, 3), 120, dtype=np.uint8)
    cv2.circle(f1, (135, 240), 50, (30, 30, 200), -1)
    f2 = f1.copy()

    fails, warnings, metrics = check_motion([f1, f2], min_motion=0.15, max_motion=2.5)
    assert metrics["mean_motion"] < 0.05
    assert any("motion_underflow" in f["check"] for f in fails)


def test_extreme_flicker_motion_overflow():
    # Extreme random noise frame transitions simulate screen collapse / flicker
    np.random.seed(42)
    f1 = np.random.randint(0, 255, (480, 270, 3), dtype=np.uint8)
    f2 = np.random.randint(0, 255, (480, 270, 3), dtype=np.uint8)

    fails, warnings, metrics = check_motion([f1, f2], min_motion=0.15, max_motion=2.5)
    assert metrics["mean_motion"] > 2.5
    assert any("motion_overflow" in f["check"] for f in fails)


def test_normal_natural_motion():
    # Gentle translation
    f1 = np.zeros((480, 270, 3), dtype=np.uint8)
    cv2.circle(f1, (135, 240), 40, (255, 255, 255), -1)

    f2 = np.zeros((480, 270, 3), dtype=np.uint8)
    cv2.circle(f2, (139, 240), 40, (255, 255, 255), -1)  # small 4px shift

    fails, warnings, metrics = check_motion([f1, f2], min_motion=0.01, max_motion=5.0)
    assert metrics["mean_motion"] > 0.0
    assert len(fails) == 0
