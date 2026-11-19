"""Smooth speed curve interpolation mapping timeline time to source video time."""

from __future__ import annotations

from typing import List, Optional
import numpy as np
from edit.plan import SpeedKeypoint


class SpeedCurveInterpolator:
    """Calculates continuous source video time mapping under dynamic speed changes."""

    def __init__(self, keypoints: Optional[List[SpeedKeypoint]], default_speed: float = 1.0):
        self.default_speed = max(0.01, float(default_speed))
        if not keypoints:
            self.times = np.array([0.0, 1000.0], dtype=np.float64)
            self.speeds = np.array([self.default_speed, self.default_speed], dtype=np.float64)
        else:
            sorted_kps = sorted(keypoints, key=lambda k: k.t)
            # Ensure start at t=0
            times = []
            speeds = []
            if sorted_kps[0].t > 0.0:
                times.append(0.0)
                speeds.append(sorted_kps[0].x)
            for kp in sorted_kps:
                times.append(kp.t)
                speeds.append(kp.x)
            # Extend to end
            times.append(times[-1] + 1000.0)
            speeds.append(speeds[-1])

            self.times = np.array(times, dtype=np.float64)
            self.speeds = np.array(speeds, dtype=np.float64)

    def get_instantaneous_speed(self, t: float) -> float:
        """Interpolate speed multiplier at cut timeline timestamp t."""
        if t <= self.times[0]:
            return float(self.speeds[0])
        if t >= self.times[-1]:
            return float(self.speeds[-1])
        return float(np.interp(t, self.times, self.speeds))

    def map_timeline_to_source_time(self, t: float, num_integration_steps: int = 50) -> float:
        """Compute accumulated source video time at timeline time t via numerical integration.

        tau_src(t) = integral_0^t s(u) du
        """
        if t <= 0.0:
            return 0.0
        # Trapezoidal numerical integration
        u = np.linspace(0.0, t, max(2, int(num_integration_steps)))
        s_u = np.interp(u, self.times, self.speeds)
        tau_src = float(np.trapezoid(s_u, u))
        return tau_src
