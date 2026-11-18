"""Tests for 3-bus audio mixing, sidechain ducking, anti-pop fade, and loudnorm."""

import numpy as np
import pyloudnorm as pyln
from edit.audio.ducking import apply_sidechain_ducking
from edit.audio.envelope import apply_fade_in_out
from edit.audio.master import normalize_lufs_and_true_peak


def test_anti_pop_fade_in_out():
    sr = 44100
    # 1 second pure tone
    audio = np.ones((sr, 2), dtype=np.float32)
    faded = apply_fade_in_out(audio, sr=sr, fade_ms=30.0)

    # First and last samples must be 0 or very near 0 to prevent clicks
    assert abs(faded[0, 0]) < 1e-5
    assert abs(faded[-1, 0]) < 1e-5
    # Center must remain unattenuated
    assert faded[sr // 2, 0] == 1.0


def test_sidechain_ducking():
    sr = 44100
    # 2 seconds music
    music = np.ones((2 * sr, 2), dtype=np.float32) * 0.5
    # Vocal only active in second half [1s to 2s]
    vocal = np.zeros((2 * sr, 2), dtype=np.float32)
    vocal[sr:, :] = 0.8  # loud vocal bark

    ducked = apply_sidechain_ducking(
        vocal_track=vocal,
        music_track=music,
        sr=sr,
        duck_under_vocal_db=-8.0,
    )

    # Music during 0 to 0.5s should be normal
    assert np.mean(ducked[:sr // 2]) > 0.45

    # Music during 1.3 to 1.8s should be ducked by ~ -8dB (multiplier ~ 0.398)
    ducked_mean = np.mean(ducked[int(1.3 * sr):int(1.8 * sr)])
    assert ducked_mean < 0.28


def test_master_audio_lufs_and_true_peak():
    sr = 44100
    # Generate test sine mix
    t = np.linspace(0, 3.0, 3 * sr, endpoint=False)
    raw_audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    stereo = np.column_stack([raw_audio, raw_audio])

    mastered = normalize_lufs_and_true_peak(
        stereo,
        sr=sr,
        target_lufs=-14.0,
        max_true_peak_db=-1.5,
    )

    # Measure result LUFS
    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(mastered)
    assert abs(lufs - (-14.0)) < 1.0

    # True peak under -1.5 dBTP (approx 0.841 linear)
    max_peak = np.max(np.abs(mastered))
    assert max_peak <= 10.0 ** (-1.5 / 20.0) + 1e-4
