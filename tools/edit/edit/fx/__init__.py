"""Dynamic effects package."""

from edit.fx.punch_in import apply_punch_in_zoom, compute_punch_in_scale
from edit.fx.speed_curve import SpeedCurveInterpolator

__all__ = [
    "SpeedCurveInterpolator",
    "compute_punch_in_scale",
    "apply_punch_in_zoom",
]
