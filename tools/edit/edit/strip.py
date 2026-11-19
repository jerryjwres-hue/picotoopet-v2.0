"""Thumbnail strip generation (strip.jpg) displaying 1 frame per shot."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import cv2
import numpy as np


def generate_thumbnail_strip(
    shot_thumbnails: List[Dict[str, Any]],
    out_path: str | Path,
    thumb_w: int = 240,
    thumb_h: int = 426,  # 9:16 aspect ratio
) -> None:
    """Stitch representative thumbnails from each shot horizontally into a filmstrip collage."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if not shot_thumbnails:
        blank = np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)
        cv2.imwrite(str(p), blank)
        return

    cards: List[np.ndarray] = []
    for item in shot_thumbnails:
        frame: np.ndarray = item["frame"]
        shot_id: str = item["shot_id"]
        tc_label: str = item.get("timecode", "")

        # Resize to thumbnail
        resized = cv2.resize(frame, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

        # Draw overlay box at bottom of each card
        cv2.rectangle(resized, (0, thumb_h - 60), (thumb_w, thumb_h), (20, 20, 20), -1)
        # Shot ID badge
        cv2.putText(
            resized, shot_id, (10, thumb_h - 35),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2, cv2.LINE_AA,
        )
        # Timecode
        cv2.putText(
            resized, tc_label, (10, thumb_h - 12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA,
        )

        cards.append(resized)

    # Add vertical divider lines between cards
    separator = np.full((thumb_h, 4, 3), 50, dtype=np.uint8)
    separated_cards = []
    for i, c in enumerate(cards):
        separated_cards.append(c)
        if i < len(cards) - 1:
            separated_cards.append(separator)

    strip = np.hstack(separated_cards)
    cv2.imwrite(str(p), strip, [cv2.IMWRITE_JPEG_QUALITY, 92])
