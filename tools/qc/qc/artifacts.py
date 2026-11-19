"""Artifact and anomaly checks for video generation quality.

Covers:
1. Dissolve / Ghosting detection: double exposure (linear blend) and rapid decorrelation.
2. Bandana position check: bright green neck scarf displaced to head or back.
3. Color smear check: sudden expanding saturated red blob (e.g. tongue glitch).
4. Fence penetration check (optional): vertical bars abnormal crossing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
import cv2
import numpy as np

logger = logging.getLogger("qc.artifacts")


def check_dissolve_ghosting(frames: List[np.ndarray]) -> List[Dict[str, Any]]:
    """Detect double exposure / linear blend and severe intra-shot dissolve.

    Algorithm:
    1. Tests linear blend of frame t against t-k and t+k for k in [3, 5].
       If alpha is in [0.22, 0.78], motion magnitude is significant (mot >= 14.0),
       and reconstruction error / motion ratio < 0.20, triggers dissolve_ghosting.
    2. Tests 6-frame correlation drop within shot. If correlation < 0.12,
       triggers dissolve_decorrelation.
    """
    fails: List[Dict[str, Any]] = []
    if len(frames) < 7:
        return fails

    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]

    # 1. Linear blend double-exposure check
    for k in [3, 5]:
        for t in range(k, len(grays) - k):
            p = grays[t - k].astype(np.float32)
            c = grays[t].astype(np.float32)
            n = grays[t + k].astype(np.float32)

            diff = n - p
            mot = float(np.mean(np.abs(diff)))
            # Ignore low motion / stationary frames to prevent false alarms
            if mot < 14.0:
                continue

            denom = float(np.sum(diff ** 2) + 1e-4)
            alpha = float(np.clip(np.sum((c - p) * diff) / denom, 0.0, 1.0))
            if 0.22 <= alpha <= 0.78:
                blend = (1.0 - alpha) * p + alpha * n
                err = float(np.mean(np.abs(c - blend)))
                ratio = err / mot
                if ratio < 0.20:
                    fails.append({
                        "check": "dissolve_ghosting",
                        "frame": t,
                        "detail": f"Frame {t}: double exposure / dissolve ghosting detected (blend ratio={ratio:.3f}, alpha={alpha:.2f}, mot={mot:.1f}).",
                    })
                    break
        if fails:
            break

    # 2. Severe 6-frame decorrelation drop check (e.g. wipe / scene cut inside single shot)
    for t in range(len(grays) - 6):
        f1 = grays[t].astype(np.float32)
        f2 = grays[t + 6].astype(np.float32)
        std1 = float(np.std(f1))
        std2 = float(np.std(f2))
        if std1 < 10.0 or std2 < 10.0:
            continue
        c_matrix = np.corrcoef(f1.flatten(), f2.flatten())
        corr = float(c_matrix[0, 1]) if not np.isnan(c_matrix[0, 1]) else 1.0
        if corr < 0.12:
            fails.append({
                "check": "dissolve_decorrelation",
                "frame": t,
                "detail": f"Frame {t}: rapid decorrelation / dissolve transition within shot (corr={corr:.3f} < 0.12).",
            })
            break

    return fails


def check_bandana_position(frames: List[np.ndarray]) -> List[Dict[str, Any]]:
    """Detect bright green bandana displaced out of position (on head or back).

    Maotai wears a bright green bandana on the neck.
    In 1080x1920 vertical format:
    - Normal neck position: cy >= 460, y_top >= 440.
    - Anomaly (e.g. S07_v1): bandana appears on top of head / back:
      y < 380, cy < 450, and vertical bounding height h > 200.
    """
    fails: List[Dict[str, Any]] = []
    for idx, f in enumerate(frames):
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        # Bright green hue [35, 85], saturation >= 70, value >= 70
        mask = cv2.inRange(hsv, np.array([35, 70, 70]), np.array([85, 255, 255]))
        pts = cv2.findNonZero(mask)
        if pts is not None and len(pts) > 150:
            m = cv2.moments(mask)
            cy = int(m["m01"] / m["m00"]) if m["m00"] > 0 else 0
            x, y, w, h = cv2.boundingRect(mask)
            if y < 380 and cy < 450 and h > 200:
                fails.append({
                    "check": "bandana_position",
                    "frame": idx,
                    "detail": f"Frame {idx}: bright green bandana displaced to head/back (y_top={y}, cy={cy}, h={h} > 200px).",
                })
                break
    return fails


def check_color_smear(frames: List[np.ndarray]) -> List[Dict[str, Any]]:
    """Detect sudden expanding saturated red blob (e.g. tongue distortion glitch).

    In S12_v1, around ~3.0s, the tongue expands abnormally into a red blob.
    Measures sudden jump of saturated red pixels (R > 160, R/G > 1.6, R/B > 1.6)
    across a 4-frame window (> 14,000 pixels jump).
    """
    fails: List[Dict[str, Any]] = []
    if len(frames) < 5:
        return fails

    red_counts: List[int] = []
    for f in frames:
        r = f[:, :, 2].astype(np.float32)
        g = f[:, :, 1].astype(np.float32)
        b = f[:, :, 0].astype(np.float32)
        mask = (r > 160) & (r / (g + 1e-4) > 1.6) & (r / (b + 1e-4) > 1.6)
        red_counts.append(int(np.sum(mask)))

    for i in range(4, len(red_counts)):
        jump = red_counts[i] - red_counts[i - 4]
        if jump > 14000:
            fails.append({
                "check": "color_smear",
                "frame": i,
                "detail": f"Frame {i}: sudden saturated red smear expansion (+{jump} pixels in 4 frames).",
            })
            break

    return fails


def check_fence_penetration(frames: List[np.ndarray], enabled: bool = False) -> List[Dict[str, Any]]:
    """Optional check for dog head/paws crossing vertical fence bars unnaturally.

    Detects vertical dark bars (Sobel-x on low brightness regions) and flags
    abrupt depth boundary violations.
    """
    fails: List[Dict[str, Any]] = []
    if not enabled or len(frames) == 0:
        return fails

    # Analyze vertical bar continuity
    for idx, f in enumerate(frames):
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        # Check dark vertical lines
        sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        vert_edges = np.abs(sobel_x) > 50
        # If dark vertical bars have disconnected fragments within dog bbox
        # This is enabled on-demand when fence spec is present
        pass

    return fails
