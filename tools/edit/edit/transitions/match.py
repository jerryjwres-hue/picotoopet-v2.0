"""Match cut transition: short cross-dissolve (<= 6 frames) between matching compositions."""

from __future__ import annotations

from typing import Any, Dict
import cv2
import numpy as np
from edit.transitions.base import register_transition


@register_transition("match")
@register_transition("dissolve")
def transition_match_cut(
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any],
) -> np.ndarray:
    """Short cross-dissolve with smooth cosine easing."""
    # Smooth easing curve
    alpha = float(0.5 * (1.0 - np.cos(np.pi * progress)))
    # Match frame dimensions if needed
    h, w = frame_out.shape[:2]
    if frame_in.shape[:2] != (h, w):
        frame_in_resized = cv2.resize(frame_in, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        frame_in_resized = frame_in

    return cv2.addWeighted(frame_out, 1.0 - alpha, frame_in_resized, alpha, 0.0)
