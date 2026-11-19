"""Audio bus mixing and mastering package."""

from edit.audio.bus import AudioBusMixer, load_audio_file
from edit.audio.ducking import apply_sidechain_ducking
from edit.audio.envelope import apply_fade_in_out
from edit.audio.master import normalize_lufs_and_true_peak

__all__ = [
    "AudioBusMixer",
    "load_audio_file",
    "apply_fade_in_out",
    "apply_sidechain_ducking",
    "normalize_lufs_and_true_peak",
]
