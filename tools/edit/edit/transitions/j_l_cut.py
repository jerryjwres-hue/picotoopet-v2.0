"""J-cut and L-cut transition audio-video offset handling.

J-cut: audio of next shot begins `offset` seconds before the video cut.
L-cut: audio of current shot continues `offset` seconds after the video cut into next shot.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
import numpy as np
from edit.transitions.base import register_transition


@register_transition("j_cut")
@register_transition("jcut")
def transition_j_cut(
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any],
) -> np.ndarray:
    """Video cuts hard at transition boundary; audio lead is orchestrated in audio bus."""
    return frame_out if progress < 0.5 else frame_in


@register_transition("l_cut")
@register_transition("lcut")
def transition_l_cut(
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any],
) -> np.ndarray:
    """Video cuts hard at transition boundary; audio tail is orchestrated in audio bus."""
    return frame_out if progress < 0.5 else frame_in


def compute_jl_cut_audio_intervals(
    shot_video_start: float,
    shot_video_end: float,
    transition_type: str,
    offset_sec: float = 0.3,
) -> Tuple[float, float]:
    """Compute adjusted (audio_start, audio_end) timestamps for J/L cut.

    Returns:
        (audio_start, audio_end) relative to master timeline.
    """
    t_type = transition_type.lower()
    audio_start = shot_video_start
    audio_end = shot_video_end

    if t_type in ("j_cut", "jcut"):
        # Next shot audio starts earlier
        audio_start = max(0.0, shot_video_start - offset_sec)
    elif t_type in ("l_cut", "lcut"):
        # Current shot audio extends past video end
        audio_end = shot_video_end + offset_sec

    return audio_start, audio_end
