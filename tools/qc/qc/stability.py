"""Visual stability quality checks: brightness, color temperature (R/B ratio), and jumps."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


def compute_brightness(frame: np.ndarray) -> float:
    """Compute frame luminance (brightness) in range [0, 255]."""
    if frame is None or frame.size == 0:
        return 0.0
    if len(frame.shape) == 2:
        return float(np.mean(frame))
    # Frame is assumed BGR as loaded by OpenCV
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    # Rec. 601 luma
    luma = 0.299 * r.astype(np.float32) + 0.587 * g.astype(np.float32) + 0.114 * b.astype(np.float32)
    return float(np.mean(luma))


def compute_color_temp_rb_ratio(frame: np.ndarray) -> float:
    """Compute color temperature estimate via Red/Blue channel mean ratio."""
    if frame is None or frame.size == 0:
        return 1.0
    if len(frame.shape) == 2:
        return 1.0
    b = np.mean(frame[:, :, 0])
    r = np.mean(frame[:, :, 2])
    return float(r / (b + 1e-6))


def check_visual_stability(
    frames: List[np.ndarray],
    allow_light_change: bool = False,
    prev_last_frame: Optional[np.ndarray] = None,
    brightness_jump_threshold: float = 18.0,
    color_temp_jump_threshold: float = 0.25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Analyze intra-shot and cross-shot stability.

    Returns:
        (fails, warnings, metrics)
    """
    fails: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "brightness_per_frame": [],
        "color_temp_rb_per_frame": [],
        "max_brightness_jump": 0.0,
        "max_color_temp_jump": 0.0,
        "cross_shot_jump": None,
    }

    if not frames:
        return fails, warnings, metrics

    brightness_list = [compute_brightness(f) for f in frames]
    color_temp_list = [compute_color_temp_rb_ratio(f) for f in frames]

    metrics["brightness_per_frame"] = [round(b, 2) for b in brightness_list]
    metrics["color_temp_rb_per_frame"] = [round(c, 3) for c in color_temp_list]
    metrics["avg_brightness"] = round(float(np.mean(brightness_list)), 2)
    metrics["avg_color_temp_rb"] = round(float(np.mean(color_temp_list)), 3)

    # 1. Cross-shot jump against previous shot's last frame
    if prev_last_frame is not None:
        prev_b = compute_brightness(prev_last_frame)
        prev_c = compute_color_temp_rb_ratio(prev_last_frame)
        curr_b = brightness_list[0]
        curr_c = color_temp_list[0]

        b_diff = abs(curr_b - prev_b)
        c_diff = abs(curr_c - prev_c)

        cross_metrics = {
            "brightness_diff": round(b_diff, 2),
            "color_temp_diff": round(c_diff, 3),
        }
        metrics["cross_shot_jump"] = cross_metrics

        if b_diff > brightness_jump_threshold * 2.0:
            warnings.append({
                "check": "cross_shot_lighting",
                "frame": 0,
                "detail": (
                    f"Noticeable cross-shot brightness jump ({b_diff:.1f} luma diff "
                    f"from prev last frame to shot start)."
                ),
            })
        if c_diff > color_temp_jump_threshold * 1.8:
            warnings.append({
                "check": "cross_shot_color_temp",
                "frame": 0,
                "detail": (
                    f"Cross-shot color temperature jump (R/B ratio diff {c_diff:.3f})."
                ),
            })

    # 2. Intra-shot frame-to-frame jump
    max_b_jump = 0.0
    max_c_jump = 0.0

    for i in range(len(frames) - 1):
        b_jump = abs(brightness_list[i + 1] - brightness_list[i])
        c_jump = abs(color_temp_list[i + 1] - color_temp_list[i])

        if b_jump > max_b_jump:
            max_b_jump = b_jump
        if c_jump > max_c_jump:
            max_c_jump = c_jump

        if b_jump > brightness_jump_threshold:
            detail = (
                f"Sudden intra-shot brightness jump of {b_jump:.1f} between "
                f"frame {i} and {i + 1}."
            )
            if not allow_light_change:
                fails.append({
                    "check": "intra_shot_brightness_jump",
                    "frame": i + 1,
                    "detail": detail + " (allow_light_change=false)",
                })
            else:
                warnings.append({
                    "check": "intra_shot_brightness_jump",
                    "frame": i + 1,
                    "detail": detail,
                })

        if c_jump > color_temp_jump_threshold:
            warnings.append({
                "check": "intra_shot_color_temp_jump",
                "frame": i + 1,
                "detail": f"Sudden intra-shot color temperature jump {c_jump:.3f} between frame {i} and {i + 1}.",
            })

    metrics["max_brightness_jump"] = round(max_b_jump, 2)
    metrics["max_color_temp_jump"] = round(max_c_jump, 3)

    return fails, warnings, metrics
