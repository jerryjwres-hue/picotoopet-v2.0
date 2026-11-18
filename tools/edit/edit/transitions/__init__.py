"""Transition techniques package."""

from edit.transitions.base import TRANSITION_REGISTRY, apply_transition, register_transition
from edit.transitions.hard_cut import transition_hard_cut
from edit.transitions.j_l_cut import compute_jl_cut_audio_intervals, transition_j_cut, transition_l_cut
from edit.transitions.match import transition_match_cut
from edit.transitions.whip import transition_whip

__all__ = [
    "TRANSITION_REGISTRY",
    "apply_transition",
    "register_transition",
    "transition_hard_cut",
    "transition_match_cut",
    "transition_whip",
    "transition_j_cut",
    "transition_l_cut",
    "compute_jl_cut_audio_intervals",
]
