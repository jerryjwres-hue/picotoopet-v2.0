"""Three-bus audio mixer orchestrator (Vocal, Foley, Music)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import av
import numpy as np

from edit.audio.ducking import apply_sidechain_ducking
from edit.audio.envelope import apply_fade_in_out
from edit.audio.master import normalize_lufs_and_true_peak
from edit.plan import EditPlan, SFXSpec, ShotPlan

logger = logging.getLogger("edit.audio.bus")


def load_audio_file(path: str | Path, target_sr: int = 44100) -> Tuple[np.ndarray, int]:
    """Read audio track into float32 numpy array [-1.0, 1.0] stereo/mono."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Audio file not found: {p}")

    container = av.open(str(p))
    audio_streams = [s for s in container.streams if s.type == "audio"]
    if not audio_streams:
        container.close()
        raise ValueError(f"No audio stream found in {p}")

    stream = audio_streams[0]
    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=target_sr)

    chunks = []
    for frame in container.decode(stream):
        resampled_frames = resampler.resample(frame)
        for r_frame in resampled_frames:
            arr = r_frame.to_ndarray()
            # PyAV fltp format returns shape (channels, samples)
            chunks.append(arr.T)

    container.close()
    if not chunks:
        return np.zeros((1, 2), dtype=np.float32), target_sr

    data = np.concatenate(chunks, axis=0).astype(np.float32)
    return data, target_sr


class AudioBusMixer:
    """Manages 3 audio buses:

    - Bus 1: Vocal (LTX dog vocalisations)
    - Bus 2: Foley & SFX (Footsteps, bowl clinking, doors)
    - Bus 3: Music (Background score, sidechained under vocal)
    """

    def __init__(self, sample_rate: int = 44100):
        self.sr = sample_rate

    def mix_timeline(
        self,
        plan: EditPlan,
        total_duration_sec: float,
        shot_timeline_map: List[Dict[str, Any]],
    ) -> np.ndarray:
        """Render all audio buses into mastered stereo track."""
        total_samples = int(np.ceil(total_duration_sec * self.sr))
        if total_samples <= 0:
            return np.zeros((1, 2), dtype=np.float32)

        bus_vocal = np.zeros((total_samples, 2), dtype=np.float32)
        bus_foley = np.zeros((total_samples, 2), dtype=np.float32)
        bus_music = np.zeros((total_samples, 2), dtype=np.float32)

        # 1. Populate Shot Audio (Vocal & Foley)
        for item in shot_timeline_map:
            shot: ShotPlan = item["shot"]
            rec_start: float = item["rec_in"]
            rec_end: float = item["rec_out"]

            # Vocal bus
            if shot.vocal:
                vocal_src = shot.vocal.file or shot.vocal.from_video or (shot.video if getattr(shot.vocal, "from_video", None) is None and shot.vocal.file is None else None)
                if vocal_src and Path(vocal_src).is_file():
                    try:
                        v_data, _ = load_audio_file(vocal_src, target_sr=self.sr)
                        # Trim according to in/out
                        src_in_samp = int(shot.in_point * self.sr)
                        src_out_samp = int(shot.out_point * self.sr)
                        v_clip = v_data[src_in_samp:src_out_samp]
                        # Apply gain
                        gain_lin = 10.0 ** (shot.vocal.gain_db / 20.0)
                        v_clip = v_clip * gain_lin
                        # Apply 30ms anti-pop head/tail fade
                        v_clip = apply_fade_in_out(v_clip, sr=self.sr, fade_ms=30.0)

                        dest_start = max(0, int((rec_start + getattr(shot, "audio_offset", 0.0)) * self.sr))
                        dest_end = min(total_samples, dest_start + len(v_clip))
                        if dest_start < total_samples and dest_end > dest_start:
                            bus_vocal[dest_start:dest_end] += v_clip[:dest_end - dest_start]
                    except Exception as exc:
                        logger.warning(f"Could not load vocal audio from {vocal_src}: {exc}")

            # Foley bus
            if shot.foley and shot.foley.file and Path(shot.foley.file).is_file():
                try:
                    f_data, _ = load_audio_file(shot.foley.file, target_sr=self.sr)
                    src_in_samp = int(shot.in_point * self.sr)
                    src_out_samp = min(len(f_data), int(shot.out_point * self.sr))
                    f_clip = f_data[src_in_samp:src_out_samp]
                    gain_lin = 10.0 ** (shot.foley.gain_db / 20.0)
                    f_clip = f_clip * gain_lin
                    f_clip = apply_fade_in_out(f_clip, sr=self.sr, fade_ms=30.0)

                    dest_start = max(0, int(rec_start * self.sr))
                    dest_end = min(total_samples, dest_start + len(f_clip))
                    if dest_start < total_samples and dest_end > dest_start:
                        bus_foley[dest_start:dest_end] += f_clip[:dest_end - dest_start]
                except Exception as exc:
                    logger.warning(f"Could not load foley audio from {shot.foley.file}: {exc}")

        # 2. Populate Spot SFX onto Foley bus
        for sfx in plan.sfx:
            if sfx.file and Path(sfx.file).is_file():
                try:
                    sfx_data, _ = load_audio_file(sfx.file, target_sr=self.sr)
                    gain_lin = 10.0 ** (sfx.gain_db / 20.0)
                    sfx_data = apply_fade_in_out(sfx_data * gain_lin, sr=self.sr, fade_ms=15.0)

                    dest_start = int(sfx.at * self.sr)
                    dest_end = min(total_samples, dest_start + len(sfx_data))
                    if dest_start < total_samples:
                        bus_foley[dest_start:dest_end] += sfx_data[:dest_end - dest_start]
                except Exception as exc:
                    logger.warning(f"Could not load SFX {sfx.file}: {exc}")

        # 3. Populate Background Music bus with Sidechain Ducking
        music_cues: List[Any] = []
        if isinstance(plan.music, list):
            music_cues = plan.music
        elif plan.music is not None:
            music_cues = [plan.music]

        raw_music_bus = np.zeros((total_samples, 2), dtype=np.float32)

        for cue in music_cues:
            cue_file = getattr(cue, "file", None)
            if not cue_file or not Path(cue_file).is_file():
                continue
            try:
                m_data, _ = load_audio_file(cue_file, target_sr=self.sr)
                # Calculate start timestamp 'at'
                shot_idx = getattr(cue, "shot", None)
                if shot_idx is not None and 0 <= shot_idx < len(shot_timeline_map):
                    at = shot_timeline_map[shot_idx]["rec_in"] + getattr(cue, "offset", 0.0)
                else:
                    at = getattr(cue, "at", 0.0) or 0.0

                in_samp = int(getattr(cue, "in_point", 0.0) * self.sr)
                if in_samp < len(m_data):
                    m_data = m_data[in_samp:]

                dur = getattr(cue, "dur", None)
                if dur is not None and dur > 0:
                    dur_samp = int(dur * self.sr)
                    m_data = m_data[:dur_samp]

                # Base gain
                gain_db = getattr(cue, "gain_db", -14.0)
                gain_lin = 10.0 ** (gain_db / 20.0)
                m_data = m_data * gain_lin

                # Fade in / out
                fade_in_sec = getattr(cue, "fade_in", 0.3)
                m_data = apply_fade_in_out(
                    m_data,
                    sr=self.sr,
                    fade_ms=max(10.0, fade_in_sec * 1000.0),
                )

                dest_start = max(0, int(at * self.sr))
                dest_end = min(total_samples, dest_start + len(m_data))
                if dest_start < total_samples and dest_end > dest_start:
                    raw_music_bus[dest_start:dest_end] += m_data[:dest_end - dest_start]
            except Exception as exc:
                logger.warning(f"Could not load music cue {cue_file}: {exc}")

        duck_db = getattr(plan.music, "duck_under_vocal_db", -8.0) if not isinstance(plan.music, list) else -8.0
        bus_music = apply_sidechain_ducking(
            vocal_track=bus_vocal,
            music_track=raw_music_bus,
            sr=self.sr,
            duck_under_vocal_db=duck_db,
        )

        # 4. Master Mix Summing & ITU-R BS.1770-4 Normalization
        master_sum = bus_vocal + bus_foley + bus_music
        mastered = normalize_lufs_and_true_peak(
            master_sum,
            sr=self.sr,
            target_lufs=plan.loudness_lufs,
            max_true_peak_db=-1.5,
        )

        return mastered
