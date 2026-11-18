"""Audio anti-pop envelope fade-in and fade-out."""

from __future__ import annotations

import numpy as np


def apply_fade_in_out(
    audio: np.ndarray,
    sr: int = 44100,
    fade_ms: float = 30.0,
) -> np.ndarray:
    """Apply 30ms smooth cosine/half-hanning fade-in at head and fade-out at tail."""
    if audio is None or len(audio) == 0:
        return audio

    fade_samples = int(sr * (fade_ms / 1000.0))
    if fade_samples <= 0 or len(audio) < 2 * fade_samples:
        return audio.copy()

    out = audio.copy()
    # Half-cosine smooth fade curves
    t_in = np.linspace(0.0, np.pi / 2.0, fade_samples, endpoint=True)
    fade_in_curve = np.sin(t_in).astype(np.float32)

    t_out = np.linspace(np.pi / 2.0, np.pi, fade_samples, endpoint=True)
    fade_out_curve = np.sin(t_out).astype(np.float32)

    if out.ndim == 1:
        out[:fade_samples] *= fade_in_curve
        out[-fade_samples:] *= fade_out_curve
    else:
        out[:fade_samples, :] *= fade_in_curve[:, np.newaxis]
        out[-fade_samples:, :] *= fade_out_curve[:, np.newaxis]

    return out
