"""Tests for audio quality checks: LUFS, clipping, and silence."""

from pathlib import Path
import numpy as np
import pytest
from scipy.io import wavfile
from qc.audio_qc import check_audio_quality


@pytest.fixture
def synthetic_wav_factory(tmp_path):
    """Generate temporary wav files with controlled parameters."""
    def _create_wav(
        filename: str = "test.wav",
        sample_rate: int = 44100,
        duration: float = 2.0,
        freq: float = 440.0,
        amplitude: float = 0.5,
        clipped: bool = False,
        silent: bool = False,
    ) -> Path:
        p = tmp_path / filename
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        if silent:
            data = np.zeros_like(t, dtype=np.float32)
        else:
            data = amplitude * np.sin(2 * np.pi * freq * t).astype(np.float32)
            if clipped:
                # Deliberately clip samples
                data = np.clip(data * 3.0, -1.0, 1.0)

        wavfile.write(str(p), sample_rate, data)
        return p

    return _create_wav


def test_audio_normal_wav(synthetic_wav_factory):
    wav_p = synthetic_wav_factory("normal.wav", amplitude=0.3, duration=2.0)
    fails, warnings, metrics = check_audio_quality(wav_p)
    assert metrics["has_audio"] is True
    assert metrics["clipping_samples"] == 0
    assert len(fails) == 0


def test_audio_clipping_detected(synthetic_wav_factory):
    wav_p = synthetic_wav_factory("clipped.wav", amplitude=1.0, clipped=True, duration=1.0)
    fails, warnings, metrics = check_audio_quality(wav_p)
    assert metrics["clipping_samples"] > 100
    assert any("audio_clipping" in f["check"] for f in fails)


def test_audio_long_silence_detected(synthetic_wav_factory):
    wav_p = synthetic_wav_factory("silent.wav", silent=True, duration=2.5)
    fails, warnings, metrics = check_audio_quality(wav_p)
    assert len(metrics["silence_segments"]) > 0
    assert any("audio_long_silence" in w["check"] for w in warnings)
