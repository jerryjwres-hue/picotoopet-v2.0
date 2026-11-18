"""Pytest fixtures and synthetic media generation utilities for QC tests.

All test assets are generated dynamically in code using solid colors, shapes,
and synthetic sine waves. No media files are committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple
import cv2
import numpy as np
import pytest


@pytest.fixture
def synthetic_image_generator():
    """Generates synthetic RGB/BGR frames with specific drawn objects."""
    def _create_frame(
        width: int = 540,
        height: int = 960,
        bg_color: Tuple[int, int, int] = (120, 120, 120),
        draw_dog: bool = True,
        draw_bowl: bool = False,
        draw_ball: bool = False,
        draw_face: bool = False,
        light_factor: float = 1.0,
    ) -> np.ndarray:
        frame = np.full((height, width, 3), np.clip(np.array(bg_color) * light_factor, 0, 255), dtype=np.uint8)

        if draw_dog:
            # Draw distinctive Alaskan Malamute stylized silhouette at upper-center
            center_x, center_y = width // 2, height // 3
            # Large body contour (area >= 20000 px)
            cv2.ellipse(frame, (center_x, center_y + 40), (100, 140), 0, 0, 360, (35, 35, 35), -1)
            # Head with white mask
            cv2.circle(frame, (center_x, center_y - 80), 70, (45, 45, 45), -1)
            cv2.ellipse(frame, (center_x, center_y - 70), (45, 55), 0, 0, 360, (230, 230, 230), -1)
            # Nose
            cv2.circle(frame, (center_x, center_y - 55), 14, (20, 20, 20), -1)

        if draw_bowl:
            # Bowl: wide elliptical shape placed safely below dog
            bx, by = width // 2, int(height * 0.82)
            cv2.ellipse(frame, (bx, by), (80, 40), 0, 0, 360, (0, 220, 255), -1)

        if draw_ball:
            # Ball: compact circle placed at bottom-left
            ball_x, ball_y = int(width * 0.25), int(height * 0.82)
            cv2.circle(frame, (ball_x, ball_y), 35, (30, 30, 230), -1)

        if draw_face:
            # Human face outline with skin-tone in HSV
            fx, fy = int(width * 0.25), int(height * 0.25)
            # BGR: (150, 180, 235) is peach skin tone
            cv2.ellipse(frame, (fx, fy), (50, 70), 0, 0, 360, (150, 180, 235), -1)
            cv2.circle(frame, (fx - 18, fy - 15), 8, (40, 40, 40), -1)
            cv2.circle(frame, (fx + 18, fy - 15), 8, (40, 40, 40), -1)
            cv2.ellipse(frame, (fx, fy + 22), (20, 10), 0, 0, 180, (40, 40, 40), 3)

        return frame

    return _create_frame


@pytest.fixture
def synthetic_video_generator(synthetic_image_generator, tmp_path):
    """Generates a short synthetic MP4 video file with controlled motion and audio."""
    def _create_video(
        filename: str = "test_shot.mp4",
        duration_sec: float = 2.0,
        fps: int = 30,
        motion_speed: float = 2.0,
        draw_dog: bool = True,
        draw_bowl: bool = True,
    ) -> Path:
        out_path = tmp_path / filename
        width, height = 540, 960  # scaled 9:16 for fast test generation
        total_frames = int(duration_sec * fps)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))

        for i in range(total_frames):
            shift_x = int(np.sin(i * 0.1) * motion_speed * 10)
            frame = synthetic_image_generator(
                width=width,
                height=height,
                bg_color=(100, 100, 100),
                draw_dog=draw_dog,
                draw_bowl=draw_bowl,
            )
            # Add translation to create motion
            M = np.float32([[1, 0, shift_x], [0, 1, 0]])
            shifted = cv2.warpAffine(frame, M, (width, height))
            writer.write(shifted)

        writer.release()
        return out_path

    return _create_video


@pytest.fixture
def synthetic_spec_factory(tmp_path):
    """Creates a sample shot_spec.json for tests."""
    def _create_spec(
        shot_id: str = "S01",
        dogs: int = 1,
        people: int = 0,
        bowls: int = 1,
        balls: int = 0,
        faces_visible: bool = False,
        min_motion: float = 0.15,
        max_motion: float = 2.5,
        y_ratio: float = 0.20,
        allow_light_change: bool = False,
        ref_image_path: str = "",
    ) -> Path:
        spec_dict = {
            "shot_id": shot_id,
            "expect": {
                "dogs": dogs,
                "people": people,
                "bowls": bowls,
                "balls": balls,
                "faces_visible": faces_visible,
            },
            "identity_refs": {"dog": ref_image_path} if ref_image_path else {},
            "min_motion": min_motion,
            "max_motion": max_motion,
            "caption": {
                "text": "Maotai waiting for dinner",
                "y_ratio": y_ratio,
            },
            "allow_light_change": allow_light_change,
        }
        spec_path = tmp_path / f"{shot_id}_spec.json"
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec_dict, f, indent=2)
        return spec_path

    return _create_spec
