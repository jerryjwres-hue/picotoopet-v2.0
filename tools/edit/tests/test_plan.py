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


def test_edit_plan_claude_format_parsing(tmp_path):
    """Verify parsing Claude plan format (root, string transitions, multi-cue music)."""
    import json
    claude_dict = {
        "root": str(tmp_path),
        "shots": [
            {
                "video": "V2_S01.mp4",
                "in": 0.0,
                "out": 3.0,
                "ltx_db": 6,
                "transition_out": "whip_left",
                "caption": {
                    "text": "dinner is late",
                    "start": 0.2,
                    "end": 2.8,
                    "y": 0.22,
                },
            },
            {
                "video": "V2_S02.mp4",
                "in": 0.5,
                "out": 2.5,
                "audio_offset": -0.45,
                "transition_out": "match",
            },
        ],
        "music": [
            {
                "file": "music_a.flac",
                "shot": 0,
                "dur": 5.0,
                "db": -6,
                "fade_in": 0.2,
                "fade_out": 0.5,
            }
        ],
    }

    p = tmp_path / "plan_claude.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(claude_dict, f)

    plan = EditPlan.from_file(p)
    assert len(plan.shots) == 2
    assert plan.shots[0].shot_id == "S01"
    assert plan.shots[0].transition_out.type == "whip"
    assert plan.shots[0].transition_out.dir == "left"
    assert plan.shots[0].caption.y_ratio == 0.22
    assert plan.shots[0].vocal.gain_db == 6.0

    assert plan.shots[1].shot_id == "S02"
    assert plan.shots[1].audio_offset == -0.45
    assert plan.shots[1].transition_out.type == "match"

    assert isinstance(plan.music, list)
    assert len(plan.music) == 1
    assert plan.music[0].gain_db == -6.0
