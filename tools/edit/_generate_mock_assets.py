"""Helper to generate temporary mock assets for run_assemble.bat self-check."""

import json
from pathlib import Path
import cv2
import numpy as np
from scipy.io import wavfile

w, h = 540, 960
fps = 24
fourcc = cv2.VideoWriter_fourcc(*"mp4v")

# Shot 1
v1 = cv2.VideoWriter("mock_s01.mp4", fourcc, fps, (w, h))
for i in range(24):
    frame = np.full((h, w, 3), (60, 100, 180), dtype=np.uint8)
    cy = h // 2 + int(np.sin(i * 0.2) * 40)
    cv2.circle(frame, (w // 2, cy), 70, (255, 255, 255), -1)
    v1.write(frame)
v1.release()

# Shot 2
v2 = cv2.VideoWriter("mock_s02.mp4", fourcc, fps, (w, h))
for i in range(24):
    frame = np.full((h, w, 3), (180, 80, 50), dtype=np.uint8)
    cx = w // 2 + int(np.cos(i * 0.2) * 40)
    cv2.rectangle(frame, (cx - 60, h // 2 - 60), (cx + 60, h // 2 + 60), (0, 220, 255), -1)
    v2.write(frame)
v2.release()

# Audio
sr = 44100
t = np.linspace(0, 2.0, 2 * sr, endpoint=False)
music = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
wavfile.write("mock_music.wav", sr, np.column_stack([music, music]))

foley = (0.4 * np.sin(2 * np.pi * 880 * t[:sr])).astype(np.float32)
wavfile.write("mock_foley.flac", sr, np.column_stack([foley, foley]))

plan = {
    "size": [540, 960],
    "fps": 24,
    "loudness_lufs": -14,
    "shots": [
        {
            "shot_id": "S01",
            "video": "mock_s01.mp4",
            "in": 0.0,
            "out": 1.0,
            "foley": {"file": "mock_foley.flac", "gain_db": -3},
            "speed": [{"t": 0, "x": 1.0}, {"t": 0.6, "x": 0.5}],
            "punch_in": {"t": 0.2, "scale": 1.15, "dur": 0.2},
            "transition_out": {"type": "whip", "dur": 0.2, "dir": "left"},
            "caption": {"text": "he waited all day...", "start": 0.1, "end": 0.8, "y_ratio": 0.20},
        },
        {
            "shot_id": "S02",
            "video": "mock_s02.mp4",
            "in": 0.0,
            "out": 1.0,
            "caption": {"text": "Maotai dinner feast!", "start": 0.1, "end": 0.8, "y_ratio": 0.25},
        },
    ],
    "music": {"file": "mock_music.wav", "gain_db": -16, "duck_under_vocal_db": -8},
}

with open("mock_plan.json", "w", encoding="utf-8") as f:
    json.dump(plan, f, indent=2)

print("Mock assets generated successfully.")
