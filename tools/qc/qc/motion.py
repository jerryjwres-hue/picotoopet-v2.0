"""Motion analysis using Farneback optical flow."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
import cv2
import numpy as np


def compute_frame_motion(prev_frame: np.ndarray, curr_frame: np.ndarray) -> float:
    """Calculate mean optical flow magnitude between two BGR or grayscale frames."""
    if prev_frame is None or curr_frame is None:
        return 0.0

    if len(prev_frame.shape) == 3:
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    else:
        prev_gray = prev_frame

    if len(curr_frame.shape) == 3:
        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    else:
        curr_gray = curr_frame

    # Downscale large frames (e.g. 1080x1920) for fast robust flow computation
    h, w = prev_gray.shape[:2]
    target_w = 480
    if w > target_w:
        scale = target_w / float(w)
        target_h = int(h * scale)
        prev_small = cv2.resize(prev_gray, (target_w, target_h), interpolation=cv2.INTER_AREA)
        curr_small = cv2.resize(curr_gray, (target_w, target_h), interpolation=cv2.INTER_AREA)
    else:
        prev_small = prev_gray
        curr_small = curr_gray

    flow = cv2.calcOpticalFlowFarneback(
        prev_small,
        curr_small,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(np.mean(mag))


def check_motion(
    frames: List[np.ndarray],
    min_motion: float = 0.15,
    max_motion: float = 2.5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Analyze motion across consecutive frames.

    Returns:
        (fails, warnings, metrics)
    """
    fails: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "flow_magnitudes": [],
        "mean_motion": 0.0,
        "min_motion_observed": 0.0,
        "max_motion_observed": 0.0,
    }

    if len(frames) < 2:
        return fails, warnings, metrics

    flow_mags: List[float] = []
    for i in range(len(frames) - 1):
        mag = compute_frame_motion(frames[i], frames[i + 1])
        flow_mags.append(mag)

    mean_motion = float(np.mean(flow_mags))
    min_observed = float(np.min(flow_mags))
    max_observed = float(np.max(flow_mags))

    metrics["flow_magnitudes"] = [round(m, 3) for m in flow_mags]
    metrics["mean_motion"] = round(mean_motion, 3)
    metrics["min_motion_observed"] = round(min_observed, 3)
    metrics["max_motion_observed"] = round(max_observed, 3)

    # Check overall shot motion
    if mean_motion < min_motion:
        fails.append({
            "check": "motion_underflow",
            "frame": None,
            "detail": (
                f"Overall motion too low ({mean_motion:.3f} < min {min_motion}); "
                "scene appears static/frozen."
            ),
        })

    if mean_motion > max_motion:
        fails.append({
            "check": "motion_overflow",
            "frame": None,
            "detail": (
                f"Overall motion too high ({mean_motion:.3f} > max {max_motion}); "
                "signs of AI video breakdown, flickering or violent warping."
            ),
        })

    # Check per-frame sudden motion bursts / glitches
    for idx, mag in enumerate(flow_mags):
        if mag > max_motion * 1.5:
            warnings.append({
                "check": "motion_spike",
                "frame": idx + 1,
                "detail": f"Extreme motion spike ({mag:.3f} > {max_motion * 1.5:.2f}) at frame transition {idx}->{idx+1}.",
            })

    return fails, warnings, metrics
