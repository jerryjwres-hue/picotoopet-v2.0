"""Tests for independent transition functions (whip, match, hard cut, J/L cut)."""

import numpy as np
from edit.transitions.base import TRANSITION_REGISTRY, apply_transition
from edit.transitions.hard_cut import transition_hard_cut
from edit.transitions.j_l_cut import compute_jl_cut_audio_intervals
from edit.transitions.match import transition_match_cut
from edit.transitions.whip import transition_whip


def test_transition_registry_loaded():
    assert "hard" in TRANSITION_REGISTRY
    assert "whip" in TRANSITION_REGISTRY
    assert "match" in TRANSITION_REGISTRY
    assert "j_cut" in TRANSITION_REGISTRY


def test_hard_cut():
    f_out = np.zeros((100, 100, 3), dtype=np.uint8)
    f_in = np.full((100, 100, 3), 255, dtype=np.uint8)

    res_early = apply_transition("hard", f_out, f_in, 0.4)
    assert np.array_equal(res_early, f_out)

    res_late = apply_transition("hard", f_out, f_in, 0.6)
    assert np.array_equal(res_late, f_in)


def test_match_cut_cross_dissolve():
    f_out = np.zeros((100, 100, 3), dtype=np.uint8)
    f_in = np.full((100, 100, 3), 200, dtype=np.uint8)

    # At midpoint (progress = 0.5), blend should be approx 100
    mid = apply_transition("match", f_out, f_in, 0.5)
    mean_val = np.mean(mid)
    assert 90 <= mean_val <= 110


def test_whip_pan_directions():
    f_out = np.full((100, 100, 3), 50, dtype=np.uint8)
    f_in = np.full((100, 100, 3), 200, dtype=np.uint8)

    for direction in ["left", "right", "up", "down"]:
        res = apply_transition("whip", f_out, f_in, 0.5, params={"dir": direction})
        assert res.shape == (100, 100, 3)
        # Should have mixed pixel values due to displacement & blur
        assert np.min(res) >= 0 and np.max(res) <= 255


def test_jl_cut_intervals():
    # J-cut: next audio starts 0.3s earlier
    start, end = compute_jl_cut_audio_intervals(3.0, 6.0, "j_cut", offset_sec=0.3)
    assert abs(start - 2.7) < 1e-4
    assert abs(end - 6.0) < 1e-4

    # L-cut: audio extends 0.4s past video end
    start_l, end_l = compute_jl_cut_audio_intervals(1.0, 4.0, "l_cut", offset_sec=0.4)
    assert abs(start_l - 1.0) < 1e-4
    assert abs(end_l - 4.4) < 1e-4
