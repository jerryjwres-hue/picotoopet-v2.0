"""Pytest fixtures for Edit tool tests.

Generates synthetic MP4 video clips, sine wave audio files, and test plans dynamically.
Zero media files committed to the repository.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple
import cv2
import numpy as np
import pytest
from scipy.io import wavfile


@pytest.fixture
def mock_video_clip_generator(tmp_path):
    """Generate a short synthetic MP4 video clip."""
    def _create_clip(
        filename: str = "shot.mp4",
        duration_sec: float = 1.5,
        fps: int = 30,
        size: Tuple[int, int] = (540, 960),
        color: Tuple[int, int, int] = (60, 100, 180),
        draw_shape: str = "circle",
    ) -> Path:
        out_p = tmp_path / filename
        w, h = size
        total_frames = int(round(duration_sec * fps))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_p), fourcc, fps, (w, h))

        for i in range(total_frames):
            frame = np.full((h, w, 3), color, dtype=np.uint8)
            # Add motion
            cx = int(w // 2 + np.sin(i * 0.2) * 50)
            cy = int(h // 2 + np.cos(i * 0.2) * 50)

            if draw_shape == "circle":
                cv2.circle(frame, (cx, cy), 60, (255, 255, 255), -1)
            elif draw_shape == "rect":
                cv2.rectangle(frame, (cx - 50, cy - 50), (cx + 50, cy + 50), (0, 220, 255), -1)

            writer.write(frame)

        writer.release()
        return out_p

    return _create_clip


@pytest.fixture
def mock_audio_generator(tmp_path):
    """Generate synthetic WAV audio files."""
    def _create_wav(
        filename: str = "audio.wav",
        duration_sec: float = 2.0,
        freq: float = 440.0,
        sample_rate: int = 44100,
        amplitude: float = 0.4,
    ) -> Path:
        out_p = tmp_path / filename
        t = np.linspace(0.0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        # Stereo sine wave
        left = amplitude * np.sin(2.0 * np.pi * freq * t)
        right = amplitude * np.sin(2.0 * np.pi * (freq * 1.5) * t)
        stereo = np.column_stack([left, right]).astype(np.float32)

        wavfile.write(str(out_p), sample_rate, stereo)
        return out_p

    return _create_wav
