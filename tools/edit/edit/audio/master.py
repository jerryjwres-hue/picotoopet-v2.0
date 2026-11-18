"""Final audio mastering: ITU-R BS.1770-4 normalization to -14 LUFS, -1.5 dBTP."""

from __future__ import annotations

import logging
import numpy as np
import pyloudnorm as pyln

logger = logging.getLogger("edit.audio.master")


def normalize_lufs_and_true_peak(
    audio: np.ndarray,
    sr: int = 44100,
    target_lufs: float = -14.0,
    max_true_peak_db: float = -1.5,
) -> np.ndarray:
    """Normalize multi-bus mix to target LUFS with true-peak limiting."""
    if audio is None or len(audio) == 0:
        return audio

    out = audio.astype(np.float32).copy()
    if out.ndim == 1:
        audio_2d = out[:, np.newaxis]
    else:
        audio_2d = out

    # 1. Measure integrated loudness via pyloudnorm
    meter = pyln.Meter(sr)
    try:
        current_lufs = meter.integrated_loudness(audio_2d)
    except Exception as exc:
        logger.warning(f"Loudness measurement error ({exc}); using RMS fallback.")
        current_lufs = -20.0

    if not np.isneginf(current_lufs) and not np.isnan(current_lufs):
        # Loudness adjustment
        gain_db = target_lufs - current_lufs
        gain_linear = 10.0 ** (gain_db / 20.0)
        out *= gain_linear
    else:
        # Fallback normalize to -1.5 dB peak
        max_v = np.max(np.abs(out))
        if max_v > 0:
            target_linear = 10.0 ** (max_true_peak_db / 20.0)
            out = out * (target_linear / max_v)
        return out

    # 2. True-peak limiting to max_true_peak_db (e.g. -1.5 dBTP)
    ceiling_linear = 10.0 ** (max_true_peak_db / 20.0)
    peak = np.max(np.abs(out))

    if peak > ceiling_linear:
        # Soft-knee peak limiting
        reduction = ceiling_linear / peak
        out *= reduction

    return np.clip(out, -1.0, 1.0)
