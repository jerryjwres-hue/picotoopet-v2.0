"""Tests for EditPlan parsing and duration calculations."""

import pytest
from edit.plan import EditPlan, ShotPlan, SpeedKeypoint


def test_edit_plan_basic_parsing(tmp_path):
    plan_dict = {
        "size": [1080, 1920],
        "fps": 30,
        "loudness_lufs": -14,
        "shots": [
            {
                "shot_id": "S01",
                "video": "shot01.mp4",
                "in": 0.0,
                "out": 3.2,
                "speed": [{"t": 0, "x": 1.0}, {"t": 2.0, "x": 0.5}],
                "punch_in": {"t": 1.0, "scale": 1.15, "dur": 0.3},
                "transition_out": {"type": "whip", "dur": 0.25, "dir": "left"},
            }
        ],
        "music": {"file": "bgm.wav", "gain_db": -16, "duck_under_vocal_db": -8},
    }

    plan_path = tmp_path / "test_plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        import json
        json.dump(plan_dict, f)

    plan = EditPlan.from_file(plan_path)
    assert plan.size == (1080, 1920)
    assert plan.fps == 30
    assert len(plan.shots) == 1
    shot = plan.shots[0]
    assert shot.shot_id == "S01"
    assert shot.in_point == 0.0
    assert shot.out_point == 3.2
    assert shot.punch_in.scale == 1.15
    assert shot.transition_out.dir == "left"
