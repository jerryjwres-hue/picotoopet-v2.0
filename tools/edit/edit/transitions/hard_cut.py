"""Hard cut transition."""

from __future__ import annotations

from typing import Any, Dict
import numpy as np
from edit.transitions.base import register_transition


@register_transition("hard")
@register_transition("cut")
def transition_hard_cut(
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any],
) -> np.ndarray:
    """Instant switch from frame_out to frame_in."""
    return frame_out if progress < 0.5 else frame_in
