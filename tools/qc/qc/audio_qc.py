"""Audio quality control: integrated loudness (LUFS), clipping, and silence detection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import av
import numpy as np
import pyloudnorm as pyln

logger = logging.getLogger("qc.audio")


def extract_audio_array(media_path: str | Path) -> Tuple[Optional[np.ndarray], int]:
    """Extract audio data from media file into float32 numpy array and return (data, sample_rate).

    Returns:
        (audio_array, sample_rate): shape is (samples,) for mono or (samples, channels) for stereo.
        If no audio stream exists, returns (None, 0).
    """
    path = str(media_path)
    try:
        container = av.open(path)
        audio_streams = [s for s in container.streams if s.type == "audio"]
        if not audio_streams:
            container.close()
            return None, 0

        stream = audio_streams[0]
        sample_rate = stream.rate or 44100

        audio_frames = []
        for frame in container.decode(stream):
            # Convert to float32 ndarray [-1.0, 1.0]
            arr = frame.to_ndarray()
            # PyAV to_ndarray shape may be (channels, samples)
            if frame.format.name in ("s16", "s16p"):
                arr = arr.astype(np.float32) / 32768.0
            elif frame.format.name in ("s32", "s32p"):
                arr = arr.astype(np.float32) / 2147483648.0
            elif frame.format.name in ("flt", "fltp"):
                arr = arr.astype(np.float32)
            else:
                arr = arr.astype(np.float32)
                # Normalize if max value exceeds 1.0
                max_val = np.max(np.abs(arr))
                if max_val > 1.0:
                    arr = arr / max_val

            if arr.ndim == 2 and arr.shape[0] < arr.shape[1]:
                # Transpose to (samples, channels)
                arr = arr.T
            audio_frames.append(arr)

        container.close()

        if not audio_frames:
            return None, 0

        concatenated = np.concatenate(audio_frames, axis=0)
        return concatenated, sample_rate

    except Exception as exc:
        logger.warning(f"Failed to extract audio from {media_path}: {exc}")
        return None, 0


def check_audio_quality(
    media_path: str | Path,
    expected_lufs: float = -14.0,
    lufs_tolerance: float = 3.5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Analyze audio track for loudness compliance, clipping, and silence."""
    fails: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "has_audio": False,
        "sample_rate": 0,
        "duration_sec": 0.0,
        "loudness_lufs": None,
        "true_peak_db": None,
        "clipping_samples": 0,
        "silence_segments": [],
    }

    audio_data, sr = extract_audio_array(media_path)
    if audio_data is None or len(audio_data) == 0:
        return fails, warnings, metrics

    metrics["has_audio"] = True
    metrics["sample_rate"] = sr

    # Normalize dimensions: ensure 1D or 2D (samples, channels)
    if audio_data.ndim == 1:
        audio_2d = audio_data[:, np.newaxis]
    else:
        audio_2d = audio_data

    samples_count = audio_2d.shape[0]
    duration_sec = samples_count / float(sr)
    metrics["duration_sec"] = round(duration_sec, 2)

    # 1. Loudness LUFS via pyloudnorm
    try:
        meter = pyln.Meter(sr)  # BS.1770 compliant
        loudness = meter.integrated_loudness(audio_2d)
        if not np.isneginf(loudness) and not np.isnan(loudness):
            metrics["loudness_lufs"] = round(float(loudness), 2)
            if abs(loudness - expected_lufs) > lufs_tolerance:
                warnings.append({
                    "check": "audio_loudness",
                    "frame": None,
                    "detail": (
                        f"Loudness is {loudness:.1f} LUFS (target {expected_lufs:.1f} ± {lufs_tolerance} LUFS; "
                        "TikTok/IG recommends around -14 LUFS)."
                    ),
                })
        else:
            metrics["loudness_lufs"] = -70.0
            warnings.append({
                "check": "audio_silence_all",
                "frame": None,
                "detail": "Audio track appears completely silent or below measurement floor.",
            })
    except Exception as exc:
        logger.warning(f"Loudness measurement error: {exc}")

    # 2. Clipping detection
    peak_val = float(np.max(np.abs(audio_2d)))
    peak_db = 20.0 * np.log10(peak_val + 1e-9)
    metrics["true_peak_db"] = round(peak_db, 2)

    clipping_mask = np.abs(audio_2d) >= 0.999
    clip_count = int(np.sum(clipping_mask))
    metrics["clipping_samples"] = clip_count

    if clip_count > 10:
        fails.append({
            "check": "audio_clipping",
            "frame": None,
            "detail": f"Severe digital clipping detected: {clip_count} samples hit >= 0.999 (-0.01 dBFS).",
        })
    elif clip_count > 0:
        warnings.append({
            "check": "audio_peak_headroom",
            "frame": None,
            "detail": f"Minor clipping: {clip_count} samples reached digital ceiling.",
        })

    # 3. Silence segments detection (RMS < -50 dBFS lasting > 1.5s)
    block_size = int(sr * 0.1)  # 100ms blocks
    if block_size > 0 and samples_count >= block_size:
        num_blocks = samples_count // block_size
        silence_blocks = []
        silence_thresh = 10.0 ** (-50.0 / 20.0)  # -50 dBFS in linear amplitude

        for b_idx in range(num_blocks):
            blk = audio_2d[b_idx * block_size : (b_idx + 1) * block_size]
            rms = np.sqrt(np.mean(blk ** 2))
            is_silent = rms < silence_thresh
            silence_blocks.append(is_silent)

        # Find continuous silent runs
        cur_start = None
        silence_segments: List[Dict[str, float]] = []
        for i, silent in enumerate(silence_blocks):
            if silent:
                if cur_start is None:
                    cur_start = i * 0.1
            else:
                if cur_start is not None:
                    seg_dur = (i * 0.1) - cur_start
                    if seg_dur >= 1.5:
                        silence_segments.append({
                            "start": round(cur_start, 2),
                            "end": round(i * 0.1, 2),
                            "duration": round(seg_dur, 2),
                        })
                    cur_start = None

        if cur_start is not None:
            seg_dur = (num_blocks * 0.1) - cur_start
            if seg_dur >= 1.5:
                silence_segments.append({
                    "start": round(cur_start, 2),
                    "end": round(num_blocks * 0.1, 2),
                    "duration": round(seg_dur, 2),
                })

        metrics["silence_segments"] = silence_segments
        if silence_segments:
            warnings.append({
                "check": "audio_long_silence",
                "frame": None,
                "detail": f"Detected {len(silence_segments)} long silence segment(s) (>1.5s).",
            })

    return fails, warnings, metrics
