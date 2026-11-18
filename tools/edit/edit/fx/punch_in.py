"""Punch-in easing zoom dynamic camera effect."""

from __future__ import annotations

from typing import Optional
import cv2
import numpy as np
from edit.plan import PunchInSpec


def compute_punch_in_scale(t: float, punch: Optional[PunchInSpec]) -> float:
    """Calculate current zoom scale factor at time t under easing curve."""
    if punch is None:
        return 1.0
    if t < punch.t:
        return 1.0

    elapsed = t - punch.t
    if elapsed >= punch.dur:
        return float(punch.scale)

    # Smooth cubic ease-in-out curve
    p = elapsed / float(punch.dur)
    # Cubic easing: 3p^2 - 2p^3
    ease_p = 3.0 * (p ** 2) - 2.0 * (p ** 3)
    return float(1.0 + (punch.scale - 1.0) * ease_p)


def apply_punch_in_zoom(frame: np.ndarray, scale: float) -> np.ndarray:
    """Center crop and zoom frame by given scale factor."""
    if scale <= 1.001:
        return frame

    h, w = frame.shape[:2]
    # Calculate crop box centered
    new_w = int(round(w / scale))
    new_h = int(round(h / scale))

    x1 = max(0, (w - new_w) // 2)
    y1 = max(0, (h - new_h) // 2)
    x2 = min(w, x1 + new_w)
    y2 = min(h, y1 + new_h)

    cropped = frame[y1:y2, x1:x2]
    zoomed = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)
    return zoomed
