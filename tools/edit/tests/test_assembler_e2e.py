"""End-to-end multi-shot assembly test: video stitching, audio mixing, EDL & filmstrip."""

import json
from pathlib import Path
from edit.assembler import assemble_video_pipeline
from edit.cli import main
from edit.plan import EditPlan


def test_assemble_video_pipeline_e2e(mock_video_clip_generator, mock_audio_generator, tmp_path):
    # Create two synthetic video clips
    s01_video = mock_video_clip_generator("s01.mp4", duration_sec=1.2, color=(50, 100, 180), draw_shape="circle")
    s02_video = mock_video_clip_generator("s02.mp4", duration_sec=1.2, color=(180, 80, 50), draw_shape="rect")

    # Create synthetic audio assets
    music_wav = mock_audio_generator("music.wav", duration_sec=3.0, freq=300.0, amplitude=0.3)
    foley_wav = mock_audio_generator("foley.wav", duration_sec=1.0, freq=800.0, amplitude=0.4)
    sfx_wav = mock_audio_generator("door.wav", duration_sec=0.5, freq=1200.0, amplitude=0.3)

    plan_dict = {
        "size": [540, 960],  # scaled 9:16 for fast test execution
        "fps": 24,
        "loudness_lufs": -14,
        "shots": [
            {
                "shot_id": "S01",
                "video": str(s01_video),
                "in": 0.0,
                "out": 1.0,
                "vocal": {"from": str(s01_video), "gain_db": 0},
                "foley": {"file": str(foley_wav), "gain_db": -3},
                "speed": [{"t": 0, "x": 1.0}, {"t": 0.8, "x": 0.5}],
                "punch_in": {"t": 0.3, "scale": 1.15, "dur": 0.2},
                "transition_out": {"type": "whip", "dur": 0.2, "dir": "left"},
                "caption": {"text": "He waited all day...", "start": 0.1, "end": 0.8, "y_ratio": 0.20},
            },
            {
                "shot_id": "S02",
                "video": str(s02_video),
                "in": 0.0,
                "out": 1.0,
                "transition_out": {"type": "match", "dur": 0.15},
                "caption": {"text": "Time for dinner!", "start": 0.2, "end": 0.9, "y_ratio": 0.25},
            },
        ],
        "music": {"file": str(music_wav), "gain_db": -16, "duck_under_vocal_db": -8},
        "sfx": [{"file": str(sfx_wav), "at": 0.5, "gain_db": -2}],
    }

    plan_path = tmp_path / "edit_plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan_dict, f, indent=2)

    plan = EditPlan.from_file(plan_path)

    out_mp4 = tmp_path / "final.mp4"
    out_edl = tmp_path / "edl.txt"
    out_strip = tmp_path / "strip.jpg"

    result = assemble_video_pipeline(
        plan=plan,
        out_video_path=out_mp4,
        out_edl_path=out_edl,
        out_strip_path=out_strip,
    )

    assert out_mp4.is_file()
    assert out_edl.is_file()
    assert out_strip.is_file()

    assert result["shot_count"] == 2
    assert result["total_duration_sec"] > 1.0
    assert result["total_frames"] > 20

    # Verify EDL contents
    edl_content = out_edl.read_text(encoding="utf-8")
    assert "S01" in edl_content
    assert "S02" in edl_content
    assert "WHIP_LEFT" in edl_content


def test_edit_cli_e2e(mock_video_clip_generator, mock_audio_generator, tmp_path):
    s01_video = mock_video_clip_generator("cli_s01.mp4", duration_sec=1.0)
    music_wav = mock_audio_generator("cli_music.wav", duration_sec=2.0)

    plan_dict = {
        "size": [540, 960],
        "fps": 24,
        "loudness_lufs": -14,
        "shots": [
            {
                "shot_id": "S01",
                "video": str(s01_video),
                "in": 0.0,
                "out": 0.8,
            }
        ],
        "music": {"file": str(music_wav), "gain_db": -16, "duck_under_vocal_db": -8},
    }

    plan_path = tmp_path / "cli_plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan_dict, f, indent=2)

    out_mp4 = tmp_path / "cli_final.mp4"

    exit_code = main(["assemble", "--plan", str(plan_path), "--out", str(out_mp4)])
    assert exit_code == 0
    assert out_mp4.is_file()
