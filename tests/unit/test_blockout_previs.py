"""Offline Blockout export tests. Synthetic media; no actual Blockout/GPU needed."""

import json
from copy import deepcopy

import pytest

from scripts.windows.blockout_previs_verify import (
    ProbeUnavailable,
    compare_coverage,
    validate_package,
)


def _meta(camera_x=0):
    return {
        "generator": {"app": "Blockout", "schema": 1},
        "profile": {"id": "wan-2.2", "name": "Wan 2.2"},
        "shot": {
            "name": "S01", "duration": 4, "fps": 24, "aspect": "16:9",
            "sensor": "super35", "rig": "dolly", "seed": 123, "rigIntensity": 0,
        },
        "cameraMarks": [{
            "index": 1, "time": 0, "position": {"x": camera_x, "y": 2, "z": 5},
            "panDeg": 0, "tiltDeg": 0, "focalLength": 35,
        }],
        "subjects": [{
            "name": "MAOTAI", "asset": "animal.dog", "labelColor": None,
            "marks": [
                {"index": 1, "time": 0, "position": {"x": -2, "z": 0}, "gait": "walk"},
                {"index": 2, "time": 4, "position": {"x": 1, "z": 0}, "gait": "stand"},
            ],
        }],
        "warnings": [],
    }


def _package(folder, *, camera_x=0, with_depth=True):
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps(_meta(camera_x)), encoding="utf-8")
    (folder / "prompt.txt").write_text("Follow dog blocking.", encoding="utf-8")
    (folder / "README.txt").write_text("Blockout package.", encoding="utf-8")
    (folder / "S01_reference.mp4").write_bytes(b"synthetic mp4 placeholder")
    if with_depth:
        (folder / "S01_depth.mp4").write_bytes(b"synthetic depth placeholder")
    stills = folder / "stills"
    stills.mkdir()
    for name in ["S01_first.png", "S01_last.png", "S01_topdown.png"]:
        (stills / name).write_bytes(b"fixture png")
    return folder


def _probe(path):
    return {"fps": 24.0, "duration": 4.0, "width": 1280, "height": 720}


def test_single_export_pass_and_never_grants_generation(tmp_path):
    package = _package(tmp_path / "shot")
    result = validate_package(package, probe=_probe, expected_seconds=4, expected_fps=24)
    assert result["status"] == "PASS"
    assert result["errors"] == []
    assert len(result["files"]["reference"]["sha256"]) == 64
    assert result["files"]["depth"]["probe"]["fps"] == 24
    assert result["shot"]["profile_id"] == "wan-2.2"
    assert result["scene_layout_verified"] is False
    assert result["workflow_compatibility_verified"] is False
    assert result["authorized_for_generation"] is False


def test_three_coverage_shots_share_actor_path_but_not_scene_proof(tmp_path):
    shots = [
        validate_package(_package(tmp_path / f"cam{i}", camera_x=i), probe=_probe)
        for i in range(3)
    ]
    coverage = compare_coverage(shots)
    assert coverage["package_count"] == 3
    assert coverage["actor_paths_match"] is True
    assert coverage["camera_views_differ"] is True
    assert coverage["same_scene_layout_proven"] is False
    assert coverage["requires_visual_scene_review"] is True


def test_changed_actor_path_fails_coverage(tmp_path):
    folder1 = _package(tmp_path / "wide")
    folder2 = _package(tmp_path / "side", camera_x=2)
    changed = deepcopy(_meta(2))
    changed["subjects"][0]["marks"][1]["position"]["z"] = 99
    (folder2 / "metadata.json").write_text(json.dumps(changed), encoding="utf-8")
    comparison = compare_coverage([
        validate_package(folder1, probe=_probe),
        validate_package(folder2, probe=_probe),
    ])
    assert comparison["actor_paths_match"] is False


def test_missing_depth_is_advisory_and_original_pipeline_remains_possible(tmp_path):
    package = _package(tmp_path / "shot", with_depth=False)
    result = validate_package(package, probe=_probe)
    assert result["status"] == "WARN"
    assert "DEPTH_VIDEO_MISSING" in result["warnings"]
    assert "reference" in result["files"]
    assert result["authorized_for_generation"] is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"shot": {"duration": 0, "fps": 24}}, "SHOT_TIMING_INVALID"),
        ({"generator": {"app": "AnotherApp", "schema": 1}}, "NOT_BLOCKOUT_METADATA"),
        ({"generator": {"app": "Blockout", "schema": 99}},
         "UNKNOWN_BLOCKOUT_METADATA_SCHEMA"),
        ({"cameraMarks": "camera"}, "CAMERA_MARKS_INVALID"),
    ],
)
def test_rejects_invalid_metadata(tmp_path, change, reason):
    package = _package(tmp_path / "shot")
    data = _meta()
    data.update(change)
    (package / "metadata.json").write_text(json.dumps(data), encoding="utf-8")
    result = validate_package(package, probe=_probe)
    assert result["status"] == "FAIL"
    assert reason in result["errors"]


def test_probe_unavailable_not_reported_as_pass(tmp_path):
    package = _package(tmp_path / "shot")

    def cannot_probe(path):
        raise ProbeUnavailable("FFPROBE_UNAVAILABLE")

    result = validate_package(package, probe=cannot_probe)
    assert result["status"] == "UNAVAILABLE"
    assert result["errors"] == ["FFPROBE_UNAVAILABLE"]


def test_reference_duration_and_depth_alignment_checked(tmp_path):
    package = _package(tmp_path / "shot")

    def bad_probe(path):
        if path.name.endswith("_depth.mp4"):
            return {"fps": 30.0, "duration": 4.0, "width": 640, "height": 480}
        return {"fps": 24.0, "duration": 4.0, "width": 1280, "height": 720}

    result = validate_package(package, probe=bad_probe, expected_seconds=3)
    assert result["status"] == "FAIL"
    assert "SHOT_DURATION_NOT_EXPECTED" in result["errors"]
    assert "DEPTH_PASS_NOT_ALIGNED" in result["errors"]


def test_untrusted_symlinked_video_is_rejected(tmp_path):
    package = _package(tmp_path / "shot")
    media = package / "S01_reference.mp4"
    media.unlink()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    try:
        media.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this host")
    result = validate_package(package, probe=_probe)
    assert result["status"] == "FAIL"
    assert "UNSAFE_OR_MISSING_FILE" in result["errors"]


def test_oversize_media_and_missing_prompt_fail_closed(tmp_path, monkeypatch):
    from scripts.windows import blockout_previs_verify as module

    package = _package(tmp_path / "shot")
    monkeypatch.setattr(module, "_MAX_MEDIA", 3)
    large = validate_package(package, probe=_probe)
    assert large["status"] == "FAIL"
    assert "FILE_EXCEEDS_READ_BUDGET" in large["errors"]
    monkeypatch.setattr(module, "_MAX_MEDIA", 2 * 1024 * 1024 * 1024)
    (package / "prompt.txt").unlink()
    missing = validate_package(package, probe=_probe)
    assert missing["status"] == "FAIL"
    assert "UNSAFE_OR_MISSING_FILE" in missing["errors"]


def test_comfyui_template_is_never_interpreted_or_authorized(tmp_path):
    package = _package(tmp_path / "shot")
    (package / "comfyui-workflow.json").write_text(
        '{"arbitrary_untrusted_node":{"shell":"powershell.exe"}}',
        encoding="utf-8",
    )
    result = validate_package(package, probe=_probe)
    assert result["status"] == "PASS"
    assert result["workflow_compatibility_verified"] is False
    assert result["authorized_for_generation"] is False


def test_camera_and_subject_warnings_do_not_fake_evidence(tmp_path):
    package = _package(tmp_path / "shot")
    data = _meta()
    data["cameraMarks"] = []
    data["subjects"] = []
    (package / "metadata.json").write_text(json.dumps(data), encoding="utf-8")
    result = validate_package(package, probe=_probe)
    assert result["status"] == "WARN"
    assert result["actor_track_sha256"] is None
    assert "SUBJECT_TRACKS_MISSING" in result["warnings"]
