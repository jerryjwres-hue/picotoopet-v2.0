"""Dynamic sidechain ducking of background music under vocal track."""

from __future__ import annotations

import numpy as np


def apply_sidechain_ducking(
    vocal_track: np.ndarray,
    music_track: np.ndarray,
    sr: int = 44100,
    duck_under_vocal_db: float = -8.0,
    threshold_db: float = -38.0,
    attack_ms: float = 40.0,
    release_ms: float = 250.0,
) -> np.ndarray:
    """Attenuate music track when vocal track energy exceeds threshold."""
    if music_track is None or len(music_track) == 0:
        return music_track
    if vocal_track is None or len(vocal_track) == 0:
        return music_track.copy()

    total_len = len(music_track)
    vocal_mono = vocal_track[:total_len]
    if vocal_mono.ndim > 1:
        vocal_mono = np.mean(vocal_mono, axis=1)

    # Pad vocal if shorter than music
    if len(vocal_mono) < total_len:
        vocal_mono = np.pad(vocal_mono, (0, total_len - len(vocal_mono)))

    # Compute short-term RMS envelope (20ms window)
    window_size = max(1, int(sr * 0.02))
    vocal_sq = vocal_mono ** 2
    # Moving average via cumulative sum
    cumsum = np.cumsum(np.insert(vocal_sq, 0, 0))
    rms = np.sqrt(np.maximum(0, (cumsum[window_size:] - cumsum[:-window_size]) / float(window_size)))
    rms = np.pad(rms, (0, total_len - len(rms)), mode="edge")

    thresh_linear = 10.0 ** (threshold_db / 20.0)
    duck_gain = 10.0 ** (duck_under_vocal_db / 20.0)  # e.g. -8 dB -> ~0.398

    # Target gain per sample: 1.0 (no duck) or duck_gain
    target_gain = np.where(rms > thresh_linear, duck_gain, 1.0)

    # Smooth gain using 1-pole IIR filter (attack and release)
    attack_alpha = np.exp(-1.0 / (sr * (attack_ms / 1000.0)))
    release_alpha = np.exp(-1.0 / (sr * (release_ms / 1000.0)))

    smoothed_gain = np.ones(total_len, dtype=np.float32)
    cur_gain = 1.0

    for i in range(total_len):
        tgt = target_gain[i]
        alpha = attack_alpha if tgt < cur_gain else release_alpha
        cur_gain = alpha * cur_gain + (1.0 - alpha) * tgt
        smoothed_gain[i] = cur_gain

    # Apply gain to music track
    out_music = music_track.copy()
    if out_music.ndim == 1:
        out_music *= smoothed_gain
    else:
        out_music *= smoothed_gain[:, np.newaxis]

    return out_music
