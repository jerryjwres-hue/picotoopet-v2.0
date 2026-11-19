"""Transition registry and extensible transition interface."""

from __future__ import annotations

from typing import Any, Callable, Dict
import numpy as np

TransitionFunc = Callable[[np.ndarray, np.ndarray, float, Dict[str, Any]], np.ndarray]

TRANSITION_REGISTRY: Dict[str, TransitionFunc] = {}


def register_transition(name: str):
    """Decorator to register a transition function."""
    def decorator(fn: TransitionFunc) -> TransitionFunc:
        TRANSITION_REGISTRY[name.lower()] = fn
        return fn
    return decorator


def apply_transition(
    type_name: str,
    frame_out: np.ndarray,
    frame_in: np.ndarray,
    progress: float,
    params: Dict[str, Any] | None = None,
) -> np.ndarray:
    """Apply transition between outgoing and incoming frames at given progress [0.0, 1.0]."""
    progress = max(0.0, min(1.0, float(progress)))
    key = type_name.lower()
    p = dict(params or {})
    if key.startswith("whip_"):
        p["dir"] = key.split("_", 1)[1]
        key = "whip"
    elif key in ("cut", "hard_cut"):
        key = "hard"

    fn = TRANSITION_REGISTRY.get(key)
    if fn is None:
        # Default fallback is hard cut
        fn = TRANSITION_REGISTRY.get("hard")
    if fn is None:
        return frame_out if progress < 0.5 else frame_in
    return fn(frame_out, frame_in, progress, p)
