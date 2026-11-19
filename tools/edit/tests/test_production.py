"""Synthetic media regression tests for the production FFmpeg entry points."""

import hashlib
import json
import subprocess

import pytest
from edit.cli import main
from edit.production import assemble_job, executor_plan, local_media


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_cli_relocated_root(tmp_path, mock_video_clip_generator, mock_audio_generator):
    clip = mock_video_clip_generator("shot.mp4", size=(96, 160))
    tone = mock_audio_generator("tone.wav")
    plan = {
        "root": "/previous/location",
        "size": [96, 160],
        "fps": 24,
        "shots": [
            {
                "video": clip.name,
                "in": 0.1,
                "out": 1.1,
                "transition_out": "dip",
                "caption": {"text": "50%: x's", "start": 0, "end": 0.7},
                "punch_in": {"t": 0.2, "scale": 1.2, "dur": 0.15},
            },
            {
                "video": clip.name,
                "out": 1.2,
                "speed": 1.5,
                "audio_offset": -0.1,
                "foley": {"file": tone.name, "db": -4},
            },
        ],
        "music": [{"file": tone.name, "shot": 0, "dur": 0.7}, {"file": tone.name, "shot": 1}],
        "sfx": [{"file": tone.name, "at": 0.4}],
    }
    plan_path = tmp_path / "edit.json"
    plan_path.write_text(json.dumps(plan))
    out = tmp_path / "cut.mp4"
    strip = tmp_path / "strip.jpg"
    assert (
        main(
            [
                "assemble",
                "--plan",
                str(plan_path),
                "--root",
                str(tmp_path),
                "--out",
                str(out),
                "--strip",
                str(strip),
            ]
        )
        == 0
    )
    assert strip.stat().st_size > 0
    rows = (tmp_path / "edl.txt").read_text().splitlines()
    assert rows == ["S01\t0.00\t1.00\tdip", "S02\t0.70\t0.80\tcut"]
    duration = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)]
    )
    assert float(duration) == pytest.approx(1.5, abs=0.1)
    audio = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(out), "-vn", "-f", "s16le", "-"]
    )
    assert any(audio)


def test_reviewed_job_mixed_transitions(tmp_path, mock_video_clip_generator, mock_audio_generator):
    clip = mock_video_clip_generator("clip.mp4", size=(96, 160))
    sound = mock_audio_generator("foley.wav")
    media_ref = {"file": sound.name, "sha256": digest(sound)}
    jobs = {"shots": [], "edit": {"fps": 24, "size": [96, 160], "loudness_lufs": -14}}
    for i, kind in enumerate(["j_cut", "whip", "speed_ramp", "l_cut", "match", "cut"]):
        jobs["shots"].append(
            {
                "shot_id": f"S{i + 1}",
                "path": clip.name,
                "sha256": digest(clip),
                "seconds": 0.8,
                "audio": {"vocal_from": "none", "foley": ["footsteps"], "music_cue": None},
                "foley_tracks": [media_ref],
                "caption": "hello" if i == 1 else None,
                "transition_out": {
                    "type": kind,
                    "offset_s": 0.12 if kind in {"j_cut", "l_cut"} else 0.0,
                },
            }
        )

    def resolve(x):
        return tmp_path / x

    plan = executor_plan(jobs, resolve, digest)
    assert plan["shots"][1]["audio_offset"] == -0.12
    assert plan["shots"][3]["audio_tail"] == 0.12
    result = assemble_job(
        jobs, tmp_path / "result.mp4", resolve=resolve, digest=digest, media=local_media
    )
    assert len(result) == 6
    assert (tmp_path / "result.mp4").stat().st_size > 0
    media_ref["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest changed"):
        executor_plan(jobs, resolve, digest)
