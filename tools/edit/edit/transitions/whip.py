"""Whip pan transition: directional motion blur and fast spatial translation in 4 directions."""

from __future__ import annotations

from typing import Any, Dict
import cv2
import numpy as np
from edit.transitions.base import register_transition


def create_motion_blur_kernel(size: int, direction: str) -> np.ndarray:
    """Create 1D directional blur kernel."""
    size = max(1, int(size))
    if size % 2 == 0:
        size += 1
    kernel = np.zeros((size, size), dtype=np.float32)

    if direction in ("left", "right"):
        kernel[size // 2, :] = 1.0 / size
    elif direction in ("up", "down"):
        kernel[:, size // 2] = 1.0 / size
    else:
        # Default horizontal
        kernel[size // 2, :] = 1.0 / size
    return kernel


@register_transition("whip")
@register_transition("whip_pan")
def transition_whip(
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any],
) -> np.ndarray:
    """Whip pan transition combining translational displacement and directional motion blur."""
    direction = str(params.get("dir", "left")).lower()
    h, w = frame_out.shape[:2]

    if frame_in.shape[:2] != (h, w):
        frame_in = cv2.resize(frame_in, (w, h), interpolation=cv2.INTER_LINEAR)

    # Nonlinear fast-in fast-out acceleration easing
    # Peak speed occurs at progress = 0.5
    ease_p = float(0.5 - 0.5 * np.cos(np.pi * progress))

    # Calculate motion blur strength (maximum in the middle of whip)
    blur_intensity = int(np.sin(np.pi * progress) * 35.0)
    if blur_intensity > 2:
        kernel = create_motion_blur_kernel(blur_intensity, direction)
        blurred_out = cv2.filter2D(frame_out, -1, kernel)
        blurred_in = cv2.filter2D(frame_in, -1, kernel)
    else:
        blurred_out = frame_out
        blurred_in = frame_in

    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    if direction == "left":
        # Outgoing moves from 0 to -w, incoming enters from w to 0
        shift = int(ease_p * w)
        # Draw outgoing part
        if shift < w:
            canvas[:, :w - shift] = blurred_out[:, shift:]
        # Draw incoming part
        if shift > 0:
            canvas[:, w - shift:] = blurred_in[:, :shift]

    elif direction == "right":
        # Outgoing moves from 0 to w, incoming enters from -w to 0
        shift = int(ease_p * w)
        if shift < w:
            canvas[:, shift:] = blurred_out[:, :w - shift]
        if shift > 0:
            canvas[:, :shift] = blurred_in[:, w - shift:]

    elif direction == "up":
        # Outgoing moves up 0 to -h, incoming enters from bottom h to 0
        shift = int(ease_p * h)
        if shift < h:
            canvas[:h - shift, :] = blurred_out[shift:, :]
        if shift > 0:
            canvas[h - shift:, :] = blurred_in[:shift, :]

    elif direction == "down":
        # Outgoing moves down 0 to h, incoming enters from top -h to 0
        shift = int(ease_p * h)
        if shift < h:
            canvas[shift:, :] = blurred_out[:h - shift, :]
        if shift > 0:
            canvas[:shift, :] = blurred_in[h - shift:, :]

    else:
        # Fallback left
        shift = int(ease_p * w)
        if shift < w:
            canvas[:, :w - shift] = blurred_out[:, shift:]
        if shift > 0:
            canvas[:, w - shift:] = blurred_in[:, :shift]

    return canvas
