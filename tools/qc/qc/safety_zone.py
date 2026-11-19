"""TikTok / Instagram UI safety occlusion zone validator for 1080x1920 canvas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from qc.spec import CaptionSpec

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

# Occlusion boundaries on 1080x1920 canvas
OCCLUSION_TOP = 160        # y < 160 (Status bar, Search, Tabs)
OCCLUSION_BOTTOM = 420     # y > 1500 (Account handle, sound title, bottom nav bar)
OCCLUSION_RIGHT = 140      # x > 940 (Profile avatar, Like, Comment, Share buttons)

SAFE_Y_MIN = OCCLUSION_TOP
SAFE_Y_MAX = CANVAS_HEIGHT - OCCLUSION_BOTTOM  # 1500
SAFE_X_MIN = 40
SAFE_X_MAX = CANVAS_WIDTH - OCCLUSION_RIGHT    # 940


def check_caption_spec_safety(
    caption: Optional[CaptionSpec],
    canvas_w: int = CANVAS_WIDTH,
    canvas_h: int = CANVAS_HEIGHT,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate that specified caption layout coordinates do not land in occlusion zones."""
    fails: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {"caption_checked": False}

    if not caption or not caption.text:
        return fails, metrics

    metrics["caption_checked"] = True
    metrics["text"] = caption.text
    metrics["y_ratio"] = caption.y_ratio

    # Calculate approximate y position in pixels
    y_px = caption.y_ratio * canvas_h
    metrics["calculated_y_px"] = round(y_px, 1)

    # Estimate text height buffer (~80px for subtitle font)
    est_top = max(0.0, y_px - 40.0)
    est_bottom = min(float(canvas_h), y_px + 40.0)

    if est_top < OCCLUSION_TOP:
        fails.append({
            "check": "subtitle_safety_zone_top",
            "frame": None,
            "detail": (
                f"Caption '{caption.text}' at y={y_px:.1f}px (ratio {caption.y_ratio:.2f}) "
                f"intrudes into top occlusion zone (top {OCCLUSION_TOP}px reserved for TikTok/IG UI)."
            ),
        })

    if est_bottom > (canvas_h - OCCLUSION_BOTTOM):
        fails.append({
            "check": "subtitle_safety_zone_bottom",
            "frame": None,
            "detail": (
                f"Caption '{caption.text}' at y={y_px:.1f}px (ratio {caption.y_ratio:.2f}) "
                f"intrudes into bottom occlusion zone (bottom {OCCLUSION_BOTTOM}px reserved for captions/profile/audio UI)."
            ),
        })

    return fails, metrics


def detect_occluded_text_in_frame(
    frame: np.ndarray,
    canvas_w: int = CANVAS_WIDTH,
    canvas_h: int = CANVAS_HEIGHT,
) -> List[Dict[str, Any]]:
    """Detect burned-in text artifacts within TikTok/IG occlusion zones."""
    issues: List[Dict[str, Any]] = []
    if frame is None or frame.size == 0:
        return issues

    h, w = frame.shape[:2]
    # Resize to standard canvas size for consistent pixel measurement if needed
    if w != canvas_w or h != canvas_h:
        frame_std = cv2.resize(frame, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)
    else:
        frame_std = frame

    gray = cv2.cvtColor(frame_std, cv2.COLOR_BGR2GRAY)

    # Create masks for the three occlusion zones
    mask_top = np.zeros_like(gray, dtype=np.uint8)
    mask_top[:OCCLUSION_TOP, :] = 255

    mask_bottom = np.zeros_like(gray, dtype=np.uint8)
    mask_bottom[canvas_h - OCCLUSION_BOTTOM:, :] = 255

    mask_right = np.zeros_like(gray, dtype=np.uint8)
    mask_right[:, canvas_w - OCCLUSION_RIGHT:] = 255

    # Look for sharp high-contrast text strokes: Sobel edge density & threshold
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edge_mag = cv2.magnitude(sobel_x, sobel_y)
    sharp_edges = (edge_mag > 150).astype(np.uint8) * 255

    # Check density of high-contrast text edges in critical regions
    def check_region(mask: np.ndarray, name: str, threshold_density: float = 0.045):
        region_pixels = cv2.countNonZero(mask)
        if region_pixels == 0:
            return
        edge_pixels = cv2.countNonZero(cv2.bitwise_and(sharp_edges, mask))
        density = edge_pixels / float(region_pixels)
        if density > threshold_density:
            issues.append({
                "zone": name,
                "edge_density": round(density, 4),
            })

    check_region(mask_top, "top_occlusion", 0.05)
    check_region(mask_bottom, "bottom_occlusion", 0.06)
    check_region(mask_right, "right_occlusion", 0.05)

    return issues
